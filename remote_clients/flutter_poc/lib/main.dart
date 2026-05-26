import 'dart:convert';
import 'dart:ui';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

void main() {
  runApp(const HomeworkHelperFlutterPoc());
}

class HomeworkHelperFlutterPoc extends StatelessWidget {
  const HomeworkHelperFlutterPoc({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'HomeworkHelper Flutter POC',
      debugShowCheckedModeBanner: false,
      themeMode: ThemeMode.dark,
      darkTheme: ThemeData(
        colorScheme: ColorScheme.fromSeed(seedColor: const Color(0xFF5B8CFF), brightness: Brightness.dark),
        useMaterial3: true,
        fontFamily: 'sans',
      ),
      home: const FixtureHomeScreen(),
    );
  }
}

class FixtureHomeScreen extends StatefulWidget {
  const FixtureHomeScreen({super.key});

  @override
  State<FixtureHomeScreen> createState() => _FixtureHomeScreenState();
}

class _FixtureHomeScreenState extends State<FixtureHomeScreen> {
  late Future<List<GameFixture>> _games;

  @override
  void initState() {
    super.initState();
    _games = _loadGames();
  }

  Future<List<GameFixture>> _loadGames() async {
    final raw = await rootBundle.loadString('assets/remote_processes.sample.json');
    final data = jsonDecode(raw) as List<dynamic>;
    return data.map((item) => GameFixture.fromJson(item as Map<String, dynamic>)).toList();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Container(
        decoration: const BoxDecoration(
          gradient: LinearGradient(
            begin: Alignment.topLeft,
            end: Alignment.bottomRight,
            colors: [Color(0xFF101827), Color(0xFF202230), Color(0xFF111827)],
          ),
        ),
        child: SafeArea(
          child: FutureBuilder<List<GameFixture>>(
            future: _games,
            builder: (context, snapshot) {
              final games = snapshot.data ?? const <GameFixture>[];
              return ListView(
                padding: const EdgeInsets.fromLTRB(18, 18, 18, 28),
                children: [
                  const HeroHeader(),
                  const SizedBox(height: 18),
                  for (final game in games) ...[
                    GameCard(game: game),
                    const SizedBox(height: 12),
                  ],
                  const SizedBox(height: 8),
                  const PowerDock(),
                ],
              );
            },
          ),
        ),
      ),
    );
  }
}

class HeroHeader extends StatelessWidget {
  const HeroHeader({super.key});

  @override
  Widget build(BuildContext context) {
    return GlassPanel(
      child: Row(
        children: [
          const Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('HomeworkHelper', style: TextStyle(fontSize: 28, fontWeight: FontWeight.w800)),
                SizedBox(height: 6),
                Text('Flutter visual fixture · host state mirror', style: TextStyle(color: Colors.white70)),
              ],
            ),
          ),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
            decoration: BoxDecoration(color: const Color(0xFF163F2A), borderRadius: BorderRadius.circular(999)),
            child: const Text('페어링됨', style: TextStyle(color: Color(0xFF5DFF8D), fontWeight: FontWeight.w700)),
          ),
        ],
      ),
    );
  }
}

class GameCard extends StatelessWidget {
  const GameCard({required this.game, super.key});

  final GameFixture game;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return GlassPanel(
      padding: const EdgeInsets.all(14),
      child: Row(
        children: [
          CircleAvatar(
            radius: 27,
            backgroundColor: game.running ? const Color(0xFF285CFF) : const Color(0xFF384054),
            child: Text((game.name.isNotEmpty ? game.name.substring(0, 1) : '?'), style: const TextStyle(fontSize: 22, fontWeight: FontWeight.w900)),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(game.name, maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w800)),
                const SizedBox(height: 7),
                ClipRRect(
                  borderRadius: BorderRadius.circular(999),
                  child: LinearProgressIndicator(
                    value: game.percentage / 100,
                    minHeight: 8,
                    backgroundColor: Colors.white.withOpacity(0.10),
                    color: game.source == 'server_tracked' ? const Color(0xFF67D95A) : scheme.primary,
                  ),
                ),
                const SizedBox(height: 6),
                Row(
                  children: [
                    Text(game.displayText, style: const TextStyle(fontWeight: FontWeight.w800)),
                    const SizedBox(width: 8),
                    Flexible(child: Text(game.statusText, maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(color: Colors.white60, fontSize: 12))),
                  ],
                ),
              ],
            ),
          ),
          const SizedBox(width: 10),
          FilledButton.tonalIcon(
            style: FilledButton.styleFrom(
              backgroundColor: game.running ? const Color(0xFF8F1D2D) : const Color(0xFF2D65E8),
              foregroundColor: Colors.white,
              fixedSize: const Size(94, 48),
              shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
            ),
            onPressed: () {},
            icon: Icon(game.running ? Icons.stop_rounded : Icons.play_arrow_rounded),
            label: Text(game.running ? '중단' : '실행'),
          ),
        ],
      ),
    );
  }
}

class PowerDock extends StatelessWidget {
  const PowerDock({super.key});

  @override
  Widget build(BuildContext context) {
    return GlassPanel(
      child: Row(
        children: const [
          Expanded(child: DockButton(icon: Icons.power_settings_new_rounded, label: '전원 켜기')),
          SizedBox(width: 8),
          Expanded(child: DockButton(icon: Icons.nights_stay_rounded, label: '절전')),
          SizedBox(width: 8),
          Expanded(child: DockButton(icon: Icons.restart_alt_rounded, label: '재시동')),
        ],
      ),
    );
  }
}

class DockButton extends StatelessWidget {
  const DockButton({required this.icon, required this.label, super.key});

  final IconData icon;
  final String label;

  @override
  Widget build(BuildContext context) {
    return Container(
      height: 72,
      decoration: BoxDecoration(color: Colors.white.withOpacity(0.08), borderRadius: BorderRadius.circular(18)),
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Icon(icon, size: 23),
          const SizedBox(height: 4),
          Text(label, style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 12)),
        ],
      ),
    );
  }
}

class GlassPanel extends StatelessWidget {
  const GlassPanel({required this.child, this.padding = const EdgeInsets.all(18), super.key});

  final Widget child;
  final EdgeInsetsGeometry padding;

  @override
  Widget build(BuildContext context) {
    return ClipRRect(
      borderRadius: BorderRadius.circular(28),
      child: BackdropFilter(
        filter: ImageFilter.blur(sigmaX: 18, sigmaY: 18),
        child: Container(
          padding: padding,
          decoration: BoxDecoration(
            color: Colors.white.withOpacity(0.10),
            borderRadius: BorderRadius.circular(28),
            border: Border.all(color: Colors.white.withOpacity(0.13)),
          ),
          child: child,
        ),
      ),
    );
  }
}

class GameFixture {
  const GameFixture({
    required this.name,
    required this.statusText,
    required this.percentage,
    required this.displayText,
    required this.source,
    required this.running,
  });

  final String name;
  final String statusText;
  final double percentage;
  final String displayText;
  final String source;
  final bool running;

  factory GameFixture.fromJson(Map<String, dynamic> json) {
    final progress = (json['progress'] as Map<String, dynamic>?) ?? const {};
    return GameFixture(
      name: json['name'] as String? ?? 'Unnamed',
      statusText: json['status_text'] as String? ?? '',
      percentage: (progress['percentage'] as num?)?.toDouble() ?? 0,
      displayText: progress['display_text'] as String? ?? '0%',
      source: progress['source'] as String? ?? 'unknown',
      running: json['is_running'] as bool? ?? false,
    );
  }
}
