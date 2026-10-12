#!/usr/bin/env python3
"""Ensure a local-only code-signing identity for HomeworkHelperRemote.

This helper intentionally creates a self-signed identity in the user's login
keychain. It is meant for personal/local builds only, not public distribution.
"""

from __future__ import annotations

import argparse
import platform
import secrets
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


DEFAULT_IDENTITY = "HomeworkHelperRemote Local Code Signing"
DEFAULT_DAYS = 3650
DEFAULT_KEYCHAIN = Path.home() / "Library" / "Keychains" / "login.keychain-db"


def _run(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        command,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if check and completed.returncode != 0:
        output = (completed.stdout or "").strip()
        raise RuntimeError(f"{command[0]} failed ({completed.returncode})\n{output}")
    return completed


def find_codesign_identity(identity: str) -> bool:
    completed = _run(["security", "find-identity", "-v", "-p", "codesigning"], check=False)
    if completed.returncode != 0:
        return False
    return any(identity in line for line in (completed.stdout or "").splitlines())


def _write_openssl_config(path: Path, identity: str) -> None:
    escaped_identity = identity.replace("\\", "\\\\").replace("\n", " ")
    path.write_text(
        f"""
[ req ]
default_bits = 2048
prompt = no
default_md = sha256
distinguished_name = dn
x509_extensions = v3_codesign

[ dn ]
CN = {escaped_identity}
O = HomeworkHelper Local
OU = Local macOS Builds

[ v3_codesign ]
basicConstraints = critical,CA:TRUE,pathlen:0
keyUsage = critical,digitalSignature,keyCertSign,cRLSign
extendedKeyUsage = codeSigning
subjectKeyIdentifier = hash
""".strip()
        + "\n",
        encoding="utf-8",
    )


def create_local_identity(identity: str, *, keychain: Path = DEFAULT_KEYCHAIN, days: int = DEFAULT_DAYS) -> None:
    if platform.system() != "Darwin":
        raise RuntimeError("macOS code-signing identity는 macOS에서만 생성할 수 있습니다.")
    if not shutil.which("openssl"):
        raise RuntimeError("openssl을 찾을 수 없습니다.")
    if not shutil.which("security"):
        raise RuntimeError("security 명령을 찾을 수 없습니다.")
    if find_codesign_identity(identity):
        print(f"✓ 기존 code-signing identity 사용: {identity}")
        return

    keychain = keychain.expanduser()
    p12_password = secrets.token_urlsafe(24)
    with tempfile.TemporaryDirectory(prefix="hhremote-codesign-") as temp:
        temp_dir = Path(temp)
        config = temp_dir / "openssl.cnf"
        key = temp_dir / "identity.key"
        cert = temp_dir / "identity.cer"
        p12 = temp_dir / "identity.p12"
        _write_openssl_config(config, identity)

        _run(
            [
                "openssl",
                "req",
                "-new",
                "-newkey",
                "rsa:2048",
                "-nodes",
                "-keyout",
                str(key),
                "-x509",
                "-days",
                str(days),
                "-out",
                str(cert),
                "-config",
                str(config),
                "-sha256",
            ]
        )
        _run(
            [
                "openssl",
                "pkcs12",
                "-export",
                "-inkey",
                str(key),
                "-in",
                str(cert),
                "-name",
                identity,
                "-out",
                str(p12),
                "-passout",
                f"pass:{p12_password}",
            ]
        )
        _run(
            [
                "security",
                "import",
                str(p12),
                "-k",
                str(keychain),
                "-P",
                p12_password,
                "-T",
                "/usr/bin/codesign",
                "-T",
                "/usr/bin/security",
            ]
        )
        _run(
            [
                "security",
                "add-trusted-cert",
                "-r",
                "trustRoot",
                "-p",
                "codeSign",
                "-k",
                str(keychain),
                str(cert),
            ]
        )

    if not find_codesign_identity(identity):
        raise RuntimeError(
            "identity를 생성했지만 codesigning identity 목록에서 확인하지 못했습니다. "
            "`security find-identity -v -p codesigning` 결과와 Keychain Access 신뢰 설정을 확인하세요."
        )
    print(f"✓ code-signing identity 준비 완료: {identity}")


def label_existing_certificates(identity: str, *, keychain: Path = DEFAULT_KEYCHAIN) -> None:
    """Change certificate labels only; preserve DER, key ACL and trust."""
    source = r'''
import Foundation
import Security
import CryptoKit
let identity = CommandLine.arguments[1]
let path = CommandLine.arguments[2]
var keychain: SecKeychain?
guard SecKeychainOpen(path, &keychain) == errSecSuccess, let keychain else { fatalError("Keychain open failed") }
let query: [CFString: Any] = [kSecClass: kSecClassCertificate, kSecMatchSearchList: [keychain],
                            kSecReturnRef: true, kSecMatchLimit: kSecMatchLimitAll]
var result: CFTypeRef?
let status = SecItemCopyMatching(query as CFDictionary, &result)
guard status == errSecSuccess, let certificates = result as? [SecCertificate] else { fatalError("Certificate lookup failed") }
var count = 0
for certificate in certificates {
    var name: CFString?
    guard SecCertificateCopyCommonName(certificate, &name) == errSecSuccess,
          name as String? == identity else { continue }
    let original = SecCertificateCopyData(certificate) as Data
    let fingerprint = Insecure.SHA1.hash(data: original).map { String(format: "%02X", $0) }.joined()
    let label = "HomeworkHelperRemote macOS Code Signing " + String(fingerprint.prefix(8))
    let selection: [CFString: Any] = [kSecClass: kSecClassCertificate, kSecMatchSearchList: [keychain], kSecValueRef: certificate]
    let updated = SecItemUpdate(selection as CFDictionary, [kSecAttrLabel: label] as CFDictionary)
    guard updated == errSecSuccess else { fatalError("Certificate label update failed: \(updated)") }
    guard SecCertificateCopyData(certificate) as Data == original else { fatalError("Certificate bytes changed") }
    print("Updated certificate label: \(label) [\(fingerprint)]")
    count += 1
}
guard count > 0 else { fatalError("No matching certificate; no certificate was created") }
'''
    with tempfile.TemporaryDirectory(prefix="hh-certificate-label-") as temp:
        program = Path(temp) / "label.swift"
        program.write_text(source, encoding="utf-8")
        result = _run(["swift", str(program), identity, str(keychain.expanduser())])
        print(result.stdout.strip())
    print("Existing certificate labels updated; signing keys and trust preserved.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Create a local-only self-signed code-signing identity for HomeworkHelperRemote."
    )
    parser.add_argument("--identity", default=DEFAULT_IDENTITY)
    parser.add_argument("--keychain", type=Path, default=DEFAULT_KEYCHAIN)
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS)
    parser.add_argument("--label-existing", action="store_true", help="Update labels without issuing a certificate")
    args = parser.parse_args(argv)

    try:
        if args.label_existing:
            label_existing_certificates(args.identity, keychain=args.keychain)
        else:
            create_local_identity(args.identity, keychain=args.keychain, days=args.days)
    except Exception as exc:
        print(f"macOS local code-signing identity 준비 실패: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
