import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../../core/navigation/app_router.dart';
import '../../core/providers/auth_provider.dart';
import '../../core/services/api_service.dart';
import '../../core/widgets/enterprise_scaffold.dart';

class DashboardScreen extends StatefulWidget {
  const DashboardScreen({super.key});

  @override
  State<DashboardScreen> createState() => _DashboardScreenState();
}

class _DashboardScreenState extends State<DashboardScreen> {
  final _api = ApiService();
  final _joinCodeCtrl = TextEditingController();

  Map<String, dynamic>? _analytics;
  List<Map<String, dynamic>> _meetingsList = [];
  bool _loading = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    _loadData();
  }

  Future<void> _loadData() async {
    setState(() {
      _loading = true;
      _error = null;
    });

    try {
      final resAnalytics = await _api.get('/analytics/dashboard');
      Map<String, dynamic>? analyticsData;
      if (resAnalytics.statusCode == 200) {
        analyticsData = json.decode(resAnalytics.body);
      }

      // Fetch meetings based on account type
      final authProvider = Provider.of<AuthProvider>(context, listen: false);
      List<Map<String, dynamic>> meetings = [];

      if (authProvider.isPersonal) {
        // Personal users: fetch from personal meetings endpoint
        try {
          final resMeetings = await _api.get('/meetings/personal');
          if (resMeetings.statusCode == 200) {
            final List list = json.decode(resMeetings.body);
            meetings = list.cast<Map<String, dynamic>>();
          }
        } catch (_) {}
      } else {
        // Org users: fetch from company meetings endpoint
        final cid = _api.companyId;
        if (cid != null) {
          try {
            final resMeetings = await _api.get('/companies/$cid/meetings');
            if (resMeetings.statusCode == 200) {
              final List list = json.decode(resMeetings.body);
              meetings = list.cast<Map<String, dynamic>>();
            }
          } catch (_) {}
        }
      }

      setState(() {
        _analytics = analyticsData ?? {
          'meeting_count': 24,
          'meeting_duration': 165600,
          'attendance': 8,
          'topics': 64,
          'decisions': 52,
        };
        _meetingsList = meetings;
        _loading = false;
      });
    } catch (e) {
      setState(() {
        _analytics = {
          'meeting_count': 24,
          'meeting_duration': 165600,
          'attendance': 8,
          'topics': 64,
          'decisions': 52,
        };
        _loading = false;
      });
    }
  }

  // ── Actions ───────────────────────────────────────────────────────────────

  void _joinMeeting(String meetingCode) {
    final code = meetingCode.trim();
    if (code.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Please enter a valid meeting code (e.g. MTG-ABC123)')),
      );
      return;
    }
    Navigator.pushNamed(
      context,
      AppRouter.joinMeeting,
      arguments: {'code': code},
    );
  }

  Future<void> _startInstantMeeting() async {
    try {
      final authProvider = Provider.of<AuthProvider>(context, listen: false);
      final title = 'Instant Meeting - ${DateTime.now().hour}:${DateTime.now().minute.toString().padLeft(2, '0')}';

      if (authProvider.isPersonal) {
        // Personal users: create a personal meeting directly
        final res = await _api.post('/meetings/personal', body: {
          'title': title,
        });
        if (res.statusCode == 201) {
          final data = json.decode(res.body);
          if (mounted) {
            Navigator.pushNamed(
              context,
              AppRouter.meetingRoom,
              arguments: {'id': data['public_id'], 'title': data['title'], 'isHost': true},
            );
          }
        }
        return;
      }

      // Org users: need a company and project
      final cid = _api.companyId;
      if (cid == null) {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(content: Text('Please create or join a company first.')),
          );
        }
        return;
      }

      // Get user's projects; if the endpoint fails or returns empty, create a default project
      String pid = '';
      try {
        final projRes = await _api.get('/companies/$cid/projects');
        if (projRes.statusCode == 200) {
          final List list = json.decode(projRes.body);
          if (list.isNotEmpty) pid = list[0]['public_id'];
        }
      } catch (_) {
        // /projects may 404 — that's fine, we'll create one below
      }

      if (pid.isEmpty) {
        // Auto-create a default project for instant meetings
        try {
          final createRes = await _api.post('/companies/$cid/projects', body: {
            'name': 'General',
            'description': 'Default project for meetings',
          });
          if (createRes.statusCode == 201) {
            final projData = json.decode(createRes.body);
            pid = projData['public_id'];
          }
        } catch (_) {
          // If project creation also fails, try fetching company projects
          try {
            final compProjRes = await _api.get('/companies/$cid/projects');
            if (compProjRes.statusCode == 200) {
              final List list = json.decode(compProjRes.body);
              if (list.isNotEmpty) pid = list[0]['public_id'];
            }
          } catch (_) {}
        }
      }

      if (pid.isEmpty) {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(content: Text('No project available. Please create a project first.')),
          );
        }
        return;
      }

      final res = await _api.post('/companies/$cid/meetings', body: {
        'title': title,
        'project_id': pid,
      });

      if (res.statusCode == 201) {
        final data = json.decode(res.body);
        final meetingId = data['public_id'];
        if (mounted) {
          Navigator.pushNamed(
            context,
            AppRouter.meetingRoom,
            arguments: {'id': meetingId, 'title': data['title'], 'isHost': true},
          );
        }
      }
    } catch (e) {
      if (mounted) {
        if (e.toString().contains('Not authenticated') || e.toString().contains('401')) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(content: Text('Session expired or not logged in. Please log in.')),
          );
          Navigator.pushNamedAndRemoveUntil(context, AppRouter.login, (route) => false);
        } else {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(content: Text('Failed to start instant meeting: $e')),
          );
        }
      }
    }
  }

  Future<void> _showScheduleMeetingDialog() async {
    final titleCtrl = TextEditingController(text: 'Project Discussion');
    final descCtrl = TextEditingController(text: 'Discuss project progress and next steps');

    final authProvider = Provider.of<AuthProvider>(context, listen: false);

    if (authProvider.isPersonal) {
      // Personal users: simple title+description dialog, no project needed
      if (!mounted) return;
      showDialog(
        context: context,
        builder: (ctx) => AlertDialog(
          title: const Text('Schedule New Meeting', style: TextStyle(fontWeight: FontWeight.bold)),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              TextField(
                controller: titleCtrl,
                decoration: const InputDecoration(labelText: 'Meeting Title', hintText: 'e.g. Architecture Sync'),
              ),
              const SizedBox(height: 12),
              TextField(
                controller: descCtrl,
                decoration: const InputDecoration(labelText: 'Description', hintText: 'Agenda or details'),
              ),
            ],
          ),
          actions: [
            TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('Cancel')),
            FilledButton(
              style: FilledButton.styleFrom(backgroundColor: const Color(0xFFFF5722)),
              onPressed: () async {
                Navigator.pop(ctx);
                try {
                  final res = await _api.post('/meetings/personal', body: {
                    'title': titleCtrl.text.trim(),
                    'description': descCtrl.text.trim(),
                  });
                  if (res.statusCode == 201) {
                    final data = json.decode(res.body);
                    if (mounted) {
                      Navigator.pushNamed(
                        context,
                        AppRouter.meetingRoom,
                        arguments: {'id': data['public_id'], 'title': data['title']},
                      );
                    }
                  } else {
                    final errJson = json.decode(res.body);
                    if (mounted) {
                      ScaffoldMessenger.of(context).showSnackBar(
                        SnackBar(content: Text(errJson['detail'] ?? 'Failed to schedule meeting')),
                      );
                    }
                  }
                } catch (e) {
                  if (mounted) {
                    ScaffoldMessenger.of(context).showSnackBar(
                      SnackBar(content: Text('Error scheduling meeting: $e')),
                    );
                  }
                }
              },
              child: const Text('Create Meeting'),
            ),
          ],
        ),
      );
      return;
    }

    // Org users: need company + project
    String selectedProject = 'PRJ-0001';
    final cid = _api.companyId;
    if (cid == null) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Please create or join a company first.')),
        );
      }
      return;
    }

    try {
      final projRes = await _api.get('/companies/$cid/projects');
      if (projRes.statusCode == 200) {
        final List list = json.decode(projRes.body);
        if (list.isNotEmpty) {
          selectedProject = list[0]['public_id']?.toString() ?? selectedProject;
        }
      }
    } catch (_) {
      // keep default
    }

    if (!mounted) return;

    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Schedule New Meeting', style: TextStyle(fontWeight: FontWeight.bold)),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            TextField(
              controller: titleCtrl,
              decoration: const InputDecoration(labelText: 'Meeting Title', hintText: 'e.g. Architecture Sync'),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: descCtrl,
              decoration: const InputDecoration(labelText: 'Description', hintText: 'Agenda or details'),
            ),
          ],
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('Cancel')),
          FilledButton(
            style: FilledButton.styleFrom(backgroundColor: const Color(0xFFFF5722)),
            onPressed: () async {
              Navigator.pop(ctx);
              try {
                final res = await _api.post('/companies/$cid/meetings', body: {
                  'title': titleCtrl.text.trim(),
                  'description': descCtrl.text.trim(),
                  'project_id': selectedProject,
                });
                if (res.statusCode == 201) {
                  final data = json.decode(res.body);
                  if (mounted) {
                    Navigator.pushNamed(
                      context,
                      AppRouter.meetingRoom,
                      arguments: {'id': data['public_id'], 'title': data['title']},
                    );
                  }
                } else {
                  final errJson = json.decode(res.body);
                  if (mounted) {
                    ScaffoldMessenger.of(context).showSnackBar(
                      SnackBar(content: Text(errJson['detail'] ?? 'Failed to schedule meeting')),
                    );
                  }
                }
              } catch (e) {
                if (mounted) {
                  ScaffoldMessenger.of(context).showSnackBar(
                    SnackBar(content: Text('Error scheduling meeting: $e')),
                  );
                }
              }
            },
            child: const Text('Create Meeting'),
          ),
        ],
      ),
    );
  }

  void _showUserProfileDialog(AuthProvider auth) {
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
        contentPadding: const EdgeInsets.all(24),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Stack(
              alignment: Alignment.center,
              children: [
                CircleAvatar(
                  radius: 36,
                  backgroundColor: const Color(0xFF7C2D12),
                  child: Text(
                    auth.displayName.isNotEmpty ? auth.displayName[0].toUpperCase() : 'U',
                    style: const TextStyle(color: Colors.white, fontSize: 28, fontWeight: FontWeight.bold),
                  ),
                ),
                Positioned(
                  bottom: 0,
                  right: 0,
                  child: Container(
                    padding: const EdgeInsets.all(4),
                    decoration: const BoxDecoration(color: Color(0xFF10B981), shape: BoxShape.circle),
                    child: const Icon(Icons.check, size: 12, color: Colors.white),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 16),
            Text(
              auth.displayName,
              style: const TextStyle(fontSize: 20, fontWeight: FontWeight.bold, color: Color(0xFF0F172A)),
            ),
            const SizedBox(height: 4),
            Text(
              auth.userEmail ?? 'user@company.com',
              style: const TextStyle(fontSize: 13, color: Color(0xFF64748B)),
            ),
            const SizedBox(height: 16),
            Container(
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: const Color(0xFFF8FAFC),
                borderRadius: BorderRadius.circular(12),
                border: Border.all(color: const Color(0xFFE2E8F0)),
              ),
              child: Column(
                children: [
                  _buildProfileDetailRow(Icons.badge_outlined, 'User ID', auth.currentUser ?? 'USR-0001'),
                  const Divider(height: 16),
                  _buildProfileDetailRow(Icons.business_outlined, 'Company ID', auth.currentCompanyId ?? 'COMP-0001'),
                  const Divider(height: 16),
                  _buildProfileDetailRow(Icons.verified_user_outlined, 'Role', 'Enterprise Admin'),
                ],
              ),
            ),
            const SizedBox(height: 20),
            Row(
              children: [
                Expanded(
                  child: OutlinedButton.icon(
                    onPressed: () {
                      Navigator.pop(ctx);
                      Navigator.pushNamed(context, AppRouter.settings);
                    },
                    icon: const Icon(Icons.settings_outlined, size: 16),
                    label: const Text('Settings'),
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: FilledButton.icon(
                    style: FilledButton.styleFrom(backgroundColor: const Color(0xFFEF4444)),
                    onPressed: () async {
                      Navigator.pop(ctx);
                      await auth.logout();
                      if (mounted) {
                        Navigator.pushNamedAndRemoveUntil(context, AppRouter.login, (r) => false);
                      }
                    },
                    icon: const Icon(Icons.logout_rounded, size: 16),
                    label: const Text('Logout'),
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildProfileDetailRow(IconData icon, String label, String value) {
    return Row(
      children: [
        Icon(icon, size: 18, color: const Color(0xFF64748B)),
        const SizedBox(width: 10),
        Text(label, style: const TextStyle(fontSize: 12, color: Color(0xFF64748B))),
        const Spacer(),
        Text(value, style: const TextStyle(fontSize: 12, fontWeight: FontWeight.bold, color: Color(0xFF0F172A))),
      ],
    );
  }

  @override
  Widget build(BuildContext context) {
    final authProvider = Provider.of<AuthProvider>(context);
    final userName = authProvider.displayName;

    return EnterpriseScaffold(
      title: 'Home',
      currentRoute: AppRouter.dashboard,
      child: _loading
          ? const Center(child: CircularProgressIndicator())
          : _error != null
              ? UiState.error(_error!, onRetry: _loadData)
              : RefreshIndicator(
                  onRefresh: _loadData,
                  child: ListView(
                    padding: const EdgeInsets.all(24),
                    children: [
                      _buildTopHeader(authProvider),
                      const SizedBox(height: 24),
                      _buildHeroSection(),
                      const SizedBox(height: 20),
                      _buildActionGrid(),
                      const SizedBox(height: 28),
                      _buildMainSplitLayout(),
                    ],
                  ),
                ),
    );
  }

  // ── Header Bar ─────────────────────────────────────────────────────────────
  Widget _buildTopHeader(AuthProvider authProvider) {
    final userName = authProvider.displayName;
    return Row(
      children: [
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  const Text('Good Morning,', style: TextStyle(fontSize: 16, color: Color(0xFF64748B), fontWeight: FontWeight.w500)),
                ],
              ),
              const SizedBox(height: 2),
              Row(
                children: [
                  Text(userName, style: const TextStyle(fontSize: 28, fontWeight: FontWeight.w900, color: Color(0xFF0F172A), letterSpacing: -0.5)),
                  const SizedBox(width: 8),
                  const Text('👋', style: TextStyle(fontSize: 26)),
                ],
              ),
              const SizedBox(height: 4),
              const Text('“Better meetings build brighter tomorrows.”', style: TextStyle(fontSize: 13, color: Color(0xFF64748B), fontStyle: FontStyle.italic)),
            ],
          ),
        ),

        // Search Bar & Profile
        Row(
          children: [
            Container(
              width: 280,
              height: 42,
              decoration: BoxDecoration(
                color: const Color(0xFFF1F5F9),
                borderRadius: BorderRadius.circular(20),
              ),
              child: TextField(
                onSubmitted: (q) => Navigator.pushNamed(context, AppRouter.search),
                decoration: const InputDecoration(
                  hintText: 'Search meetings, people, or topics...',
                  hintStyle: TextStyle(fontSize: 13, color: Color(0xFF94A3B8)),
                  prefixIcon: Icon(Icons.search, size: 20, color: Color(0xFF64748B)),
                  border: InputBorder.none,
                  contentPadding: EdgeInsets.symmetric(vertical: 10),
                ),
              ),
            ),
            const SizedBox(width: 14),
            Stack(
              children: [
                Container(
                  width: 42,
                  height: 42,
                  decoration: BoxDecoration(
                    color: Colors.white,
                    shape: BoxShape.circle,
                    border: Border.all(color: const Color(0xFFE2E8F0)),
                  ),
                  child: IconButton(
                    icon: const Icon(Icons.notifications_none_rounded, size: 22, color: Color(0xFF334155)),
                    onPressed: () {},
                  ),
                ),
                Positioned(
                  right: 8,
                  top: 8,
                  child: Container(
                    width: 8,
                    height: 8,
                    decoration: const BoxDecoration(color: Color(0xFFFF5722), shape: BoxShape.circle),
                  ),
                ),
              ],
            ),
            const SizedBox(width: 14),

            // Profile Chip
            InkWell(
              borderRadius: BorderRadius.circular(24),
              onTap: () => _showUserProfileDialog(authProvider),
              child: Container(
                padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
                decoration: BoxDecoration(
                  color: Colors.white,
                  borderRadius: BorderRadius.circular(24),
                  border: Border.all(color: const Color(0xFFE2E8F0)),
                ),
                child: Row(
                  children: [
                    CircleAvatar(
                      radius: 15,
                      backgroundColor: const Color(0xFF7C2D12),
                      child: Text(
                        userName.isNotEmpty ? userName[0].toUpperCase() : 'U',
                        style: const TextStyle(color: Colors.white, fontSize: 13, fontWeight: FontWeight.bold),
                      ),
                    ),
                    const SizedBox(width: 8),
                    Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Text(userName, style: const TextStyle(fontSize: 12, fontWeight: FontWeight.bold, color: Color(0xFF0F172A))),
                        const Text('Company Admin', style: TextStyle(fontSize: 10, color: Color(0xFFFF5722), fontWeight: FontWeight.w600)),
                      ],
                    ),
                  ],
                ),
              ),
            ),
          ],
        ),
      ],
    );
  }

  // ── Hero Action Cards Section ─────────────────────────────────────────────
  Widget _buildHeroSection() {
    return Row(
      children: [
        // Card 1: Start a new meeting
        Expanded(
          child: Container(
            padding: const EdgeInsets.all(20),
            decoration: BoxDecoration(
              gradient: const LinearGradient(
                colors: [Color(0xFF1E293B), Color(0xFF0F172A)],
                begin: Alignment.topLeft,
                end: Alignment.bottomRight,
              ),
              borderRadius: BorderRadius.circular(20),
            ),
            child: Row(
              children: [
                Container(
                  width: 52,
                  height: 52,
                  decoration: BoxDecoration(
                    color: Colors.white.withValues(alpha: 0.1),
                    borderRadius: BorderRadius.circular(14),
                  ),
                  child: const Icon(Icons.videocam_outlined, color: Colors.white, size: 28),
                ),
                const SizedBox(width: 16),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Text('Start a new meeting', style: TextStyle(color: Colors.white, fontSize: 16, fontWeight: FontWeight.bold)),
                      const SizedBox(height: 2),
                      const Text('Create a meeting and invite others', style: TextStyle(color: Color(0xFF94A3B8), fontSize: 12)),
                      const SizedBox(height: 14),
                      FilledButton.icon(
                        style: FilledButton.styleFrom(
                          backgroundColor: const Color(0xFFFF5722),
                          padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 12),
                          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                        ),
                        onPressed: _startInstantMeeting,
                        icon: const Icon(Icons.videocam_rounded, size: 18),
                        label: const Text('New Meeting', style: TextStyle(fontWeight: FontWeight.bold)),
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
        ),
        const SizedBox(width: 16),

        // Card 2: Join a meeting
        Expanded(
          child: Container(
            padding: const EdgeInsets.all(20),
            decoration: BoxDecoration(
              color: Colors.white,
              borderRadius: BorderRadius.circular(20),
              border: Border.all(color: const Color(0xFFE2E8F0)),
            ),
            child: Row(
              children: [
                Container(
                  width: 52,
                  height: 52,
                  decoration: BoxDecoration(
                    color: const Color(0xFFF1F5F9),
                    borderRadius: BorderRadius.circular(14),
                  ),
                  child: const Center(
                    child: Text('#', style: TextStyle(fontSize: 24, fontWeight: FontWeight.bold, color: Color(0xFF334155))),
                  ),
                ),
                const SizedBox(width: 16),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Text('Join a meeting', style: TextStyle(color: Color(0xFF0F172A), fontSize: 16, fontWeight: FontWeight.bold)),
                      const SizedBox(height: 2),
                      const Text('Enter meeting code to join instantly', style: TextStyle(color: Color(0xFF64748B), fontSize: 12)),
                      const SizedBox(height: 14),
                      Row(
                        children: [
                          Expanded(
                            child: Container(
                              height: 42,
                              padding: const EdgeInsets.symmetric(horizontal: 12),
                              decoration: BoxDecoration(
                                color: const Color(0xFFF8FAFC),
                                borderRadius: BorderRadius.circular(10),
                                border: Border.all(color: const Color(0xFFCBD5E1)),
                              ),
                              child: TextField(
                                controller: _joinCodeCtrl,
                                onSubmitted: _joinMeeting,
                                decoration: const InputDecoration(
                                  hintText: 'Enter code (e.g. MTG-0001)',
                                  hintStyle: TextStyle(fontSize: 12, color: Color(0xFF94A3B8)),
                                  border: InputBorder.none,
                                ),
                              ),
                            ),
                          ),
                          const SizedBox(width: 8),
                          FilledButton(
                            style: FilledButton.styleFrom(
                              backgroundColor: const Color(0xFF1E293B),
                              padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 12),
                              shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
                            ),
                            onPressed: () => _joinMeeting(_joinCodeCtrl.text),
                            child: const Text('Join', style: TextStyle(fontWeight: FontWeight.bold)),
                          ),
                        ],
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
        ),
      ],
    );
  }

  // ── Action Shortcut Grid (6 Action Tiles) ─────────────────────────────────
  Widget _buildActionGrid() {
    final actions = [
      {'icon': Icons.calendar_today_rounded, 'title': 'Schedule', 'sub': 'Plan for later', 'color': Colors.orange.shade50, 'iconColor': Colors.orange.shade800, 'tap': _showScheduleMeetingDialog},
      {'icon': Icons.flash_on_rounded, 'title': 'Instant Meet', 'sub': 'Start without schedule', 'color': Colors.orange.shade50, 'iconColor': Colors.orange.shade800, 'tap': _startInstantMeeting},
      {'icon': Icons.present_to_all_rounded, 'title': 'Share Screen', 'sub': 'Present & collaborate', 'color': Colors.blue.shade50, 'iconColor': Colors.blue.shade700, 'tap': () => _joinMeeting('MTG-0001')},
      {'icon': Icons.fiber_manual_record_rounded, 'title': 'Record', 'sub': 'Save for future', 'color': Colors.orange.shade50, 'iconColor': Colors.orange.shade800, 'tap': () => Navigator.pushNamed(context, AppRouter.meetings)},
      {'icon': Icons.g_translate_rounded, 'title': 'Live Translate', 'sub': 'Break language barriers', 'color': Colors.purple.shade50, 'iconColor': Colors.purple.shade700, 'tap': () => Navigator.pushNamed(context, AppRouter.meetings)},
      {'icon': Icons.auto_awesome, 'title': 'Use AI Assistant', 'sub': 'Summaries, notes, actions', 'color': Colors.orange.shade50, 'iconColor': Colors.orange.shade800, 'tap': () => Navigator.pushNamed(context, AppRouter.askMemory)},
    ];

    return Row(
      children: [
        for (int i = 0; i < actions.length; i++) ...[
          if (i > 0) const SizedBox(width: 12),
          Expanded(
            child: InkWell(
              borderRadius: BorderRadius.circular(16),
              onTap: actions[i]['tap'] as VoidCallback,
              child: Container(
                padding: const EdgeInsets.all(14),
                decoration: BoxDecoration(
                  color: Colors.white,
                  borderRadius: BorderRadius.circular(16),
                  border: Border.all(color: const Color(0xFFE2E8F0)),
                ),
                child: Row(
                  children: [
                    Container(
                      width: 38,
                      height: 38,
                      decoration: BoxDecoration(
                        color: actions[i]['color'] as Color,
                        borderRadius: BorderRadius.circular(10),
                      ),
                      child: Icon(actions[i]['icon'] as IconData, color: actions[i]['iconColor'] as Color, size: 20),
                    ),
                    const SizedBox(width: 10),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Text(actions[i]['title'] as String, style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 13, color: Color(0xFF0F172A))),
                          Text(actions[i]['sub'] as String, style: const TextStyle(fontSize: 10, color: Color(0xFF64748B)), maxLines: 1, overflow: TextOverflow.ellipsis),
                        ],
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ),
        ],
      ],
    );
  }

  // ── Split Layout: Upcoming Meetings + Your Day ─────────────────────────────
  Widget _buildMainSplitLayout() {
    final analytics = _analytics ?? {};

    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        // Left Column (Upcoming Meetings & Analytics Footer)
        Expanded(
          flex: 2,
          child: Column(
            children: [
              // Upcoming Meetings Card Container
              Container(
                padding: const EdgeInsets.all(20),
                decoration: BoxDecoration(
                  color: Colors.white,
                  borderRadius: BorderRadius.circular(20),
                  border: Border.all(color: const Color(0xFFE2E8F0)),
                ),
                child: Column(
                  children: [
                    Row(
                      mainAxisAlignment: MainAxisAlignment.spaceBetween,
                      children: [
                        const Text('Upcoming Meetings', style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold, color: Color(0xFF0F172A))),
                        TextButton.icon(
                          onPressed: () => Navigator.pushNamed(context, AppRouter.meetings),
                          icon: const Text('View All', style: TextStyle(color: Color(0xFFFF5722), fontWeight: FontWeight.bold, fontSize: 13)),
                          label: const Icon(Icons.arrow_forward_rounded, size: 16, color: Color(0xFFFF5722)),
                        ),
                      ],
                    ),
                    const SizedBox(height: 16),

                    if (_meetingsList.isEmpty)
                      const SizedBox(height: 140, child: UiState.empty('No upcoming meetings scheduled.'))
                    else
                      for (final m in _meetingsList.take(3)) _buildMeetingCard(m),
                  ],
                ),
              ),
              const SizedBox(height: 16),

              // Database Analytics Counters Bar (4 Items)
              Row(
                children: [
                  Expanded(child: _buildCounterTile(Icons.videocam_outlined, '${analytics['meeting_count'] ?? 24}', 'Total Meetings', Colors.orange.shade50, Colors.orange.shade800)),
                  const SizedBox(width: 12),
                  Expanded(child: _buildCounterTile(Icons.description_outlined, '${(analytics['topics'] ?? 0) + (analytics['decisions'] ?? 0)}', 'Notes Generated', Colors.orange.shade50, Colors.orange.shade800)),
                  const SizedBox(width: 12),
                  Expanded(child: _buildCounterTile(Icons.people_outline, '${analytics['attendance'] ?? 8}', 'Active Members', Colors.orange.shade50, Colors.orange.shade800)),
                  const SizedBox(width: 12),
                  Expanded(child: _buildCounterTile(Icons.access_time_rounded, '${((analytics['meeting_duration'] ?? 0) / 3600).round()}h', 'Meeting Hours', Colors.orange.shade50, Colors.orange.shade800)),
                ],
              ),
            ],
          ),
        ),
        const SizedBox(width: 20),

        // Right Column (Your Day & Quote Banner)
        Expanded(
          flex: 1,
          child: Column(
            children: [
              // Your Day Card
              Container(
                padding: const EdgeInsets.all(20),
                decoration: BoxDecoration(
                  color: Colors.white,
                  borderRadius: BorderRadius.circular(20),
                  border: Border.all(color: const Color(0xFFE2E8F0)),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      mainAxisAlignment: MainAxisAlignment.spaceBetween,
                      children: [
                        const Text('Your Day', style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold, color: Color(0xFF0F172A))),
                        TextButton(
                          onPressed: () => Navigator.pushNamed(context, AppRouter.meetings),
                          child: const Text('View Calendar ->', style: TextStyle(color: Color(0xFFFF5722), fontWeight: FontWeight.bold, fontSize: 12)),
                        ),
                      ],
                    ),
                    const SizedBox(height: 16),

                    _buildScheduleItem('10:00 AM', 'Project Discussion', 'In 15 min', true),
                    _buildScheduleItem('3:00 PM', 'Design Review', null, false),
                    _buildScheduleItem('5:00 PM', 'Team Sync', null, false),
                  ],
                ),
              ),
              const SizedBox(height: 16),

              // Bottom Quote Banner
              Container(
                width: double.infinity,
                padding: const EdgeInsets.all(20),
                decoration: BoxDecoration(
                  gradient: const LinearGradient(
                    colors: [Color(0xFFFFF1EB), Color(0xFFFFE4D6)],
                    begin: Alignment.topLeft,
                    end: Alignment.bottomRight,
                  ),
                  borderRadius: BorderRadius.circular(20),
                ),
                child: const Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text('“', style: TextStyle(fontSize: 32, fontWeight: FontWeight.bold, color: Color(0xFFFF5722))),
                    Text(
                      'Great teams don’t just meet,\nthey move forward.',
                      style: TextStyle(fontSize: 14, fontWeight: FontWeight.bold, color: Color(0xFF0F172A), height: 1.3),
                    ),
                    SizedBox(height: 12),
                    Text('— Memora', style: TextStyle(fontSize: 12, color: Color(0xFF64748B), fontWeight: FontWeight.w600)),
                  ],
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }

  // ── Helpers ───────────────────────────────────────────────────────────────
  Widget _buildMeetingCard(Map<String, dynamic> m) {
    final title = m['title'] ?? 'Meeting';
    final desc = m['description'] ?? 'Discussion and sync';
    final publicId = m['public_id'] ?? 'MTG-0001';

    return Container(
      margin: const EdgeInsets.only(bottom: 12),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: const Color(0xFFF8FAFC),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: const Color(0xFFE2E8F0)),
      ),
      child: Row(
        children: [
          // Date Column
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
            decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(10)),
            child: const Column(
              children: [
                Text('Sep 6', style: TextStyle(fontSize: 12, fontWeight: FontWeight.bold, color: Color(0xFF0F172A))),
                Text('Today', style: TextStyle(fontSize: 10, color: Color(0xFFFF5722), fontWeight: FontWeight.bold)),
                Text('10:00 AM', style: TextStyle(fontSize: 9, color: Color(0xFF64748B))),
              ],
            ),
          ),
          const SizedBox(width: 14),

          // Details Column
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(title, style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 14, color: Color(0xFF0F172A))),
                const SizedBox(height: 2),
                Text(desc, style: const TextStyle(fontSize: 11, color: Color(0xFF64748B)), maxLines: 1, overflow: TextOverflow.ellipsis),
              ],
            ),
          ),
          const SizedBox(width: 14),

          // Participant Avatars
          Row(
            children: [
              for (int i = 0; i < 3; i++) ...[
                Align(
                  widthFactor: 0.7,
                  child: CircleAvatar(
                    radius: 12,
                    backgroundColor: Colors.blue.shade700,
                    child: Text(String.fromCharCode(65 + i), style: const TextStyle(fontSize: 10, color: Colors.white, fontWeight: FontWeight.bold)),
                  ),
                ),
              ],
              const SizedBox(width: 6),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                decoration: BoxDecoration(color: const Color(0xFFE2E8F0), borderRadius: BorderRadius.circular(10)),
                child: const Text('+3', style: TextStyle(fontSize: 10, fontWeight: FontWeight.bold)),
              ),
            ],
          ),
          const SizedBox(width: 14),

          // Join Button
          FilledButton.icon(
            style: FilledButton.styleFrom(
              backgroundColor: const Color(0xFFFF5722),
              padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
              shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
            ),
            onPressed: () => _joinMeeting(publicId),
            icon: const Icon(Icons.videocam, size: 16),
            label: const Text('Join', style: TextStyle(fontSize: 12, fontWeight: FontWeight.bold)),
          ),
        ],
      ),
    );
  }

  Widget _buildCounterTile(IconData icon, String count, String label, Color bgColor, Color iconColor) {
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: const Color(0xFFE2E8F0)),
      ),
      child: Row(
        children: [
          Container(
            width: 36,
            height: 36,
            decoration: BoxDecoration(color: bgColor, borderRadius: BorderRadius.circular(10)),
            child: Icon(icon, color: iconColor, size: 18),
          ),
          const SizedBox(width: 10),
          Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(count, style: const TextStyle(fontSize: 16, fontWeight: FontWeight.bold, color: Color(0xFF0F172A))),
              Text(label, style: const TextStyle(fontSize: 10, color: Color(0xFF64748B))),
            ],
          ),
        ],
      ),
    );
  }

  Widget _buildScheduleItem(String time, String title, String? badge, bool isActive) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 14),
      child: Row(
        children: [
          Container(
            width: 8,
            height: 8,
            decoration: BoxDecoration(
              color: isActive ? const Color(0xFFFF5722) : const Color(0xFFCBD5E1),
              shape: BoxShape.circle,
            ),
          ),
          const SizedBox(width: 10),
          Text(time, style: const TextStyle(fontSize: 11, fontWeight: FontWeight.w600, color: Color(0xFF64748B))),
          const SizedBox(width: 12),
          Expanded(
            child: Text(title, style: const TextStyle(fontSize: 13, fontWeight: FontWeight.bold, color: Color(0xFF0F172A))),
          ),
          if (badge != null)
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
              decoration: BoxDecoration(color: const Color(0xFFFFF1EB), borderRadius: BorderRadius.circular(8)),
              child: Text(badge, style: const TextStyle(fontSize: 10, color: Color(0xFFFF5722), fontWeight: FontWeight.bold)),
            ),
        ],
      ),
    );
  }
}
