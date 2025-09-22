import sys
import os

# 이 런처 스크립트는 애플리케이션의 올바른 진입점입니다.

def main():
    """
    환경을 설정하고 메인 애플리케이션을 실행합니다.
    """
    # 현재 작업 디렉터리를 프로젝트 루트로 설정합니다.
    # 이렇게 하면 데이터베이스, 아이콘 등 리소스에 대한 상대 경로가 올바르게 작동합니다.
    project_root = os.path.dirname(os.path.abspath(__file__))
    os.chdir(project_root)

    # 'python' 패키지의 절대 임포트를 허용하기 위해 프로젝트 루트를 Python 경로에 추가합니다.
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    # 이제 경로가 설정되었으므로 애플리케이션 모듈을 임포트할 수 있습니다.
    from python.views.homework_helper import start_main_application, run_with_single_instance_check

    # 이전에 homework_helper.pyw의 __main__ 블록에 있던 로직입니다.
    run_with_single_instance_check(
        application_name="숙제 관리자",
        main_app_start_callback=start_main_application
    )

if __name__ == '__main__':
    main()
