import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';
import '../../core/navigation/app_router.dart';
import '../../core/providers/auth_provider.dart';
import '../../core/services/api_service.dart';
import '../../core/widgets/enterprise_scaffold.dart';

const _appBuildSha = String.fromEnvironment('APP_BUILD_SHA', defaultValue: 'local');

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
        _analytics = analyticsData ?? {};
        _meetingsList = meetings;
        _loading = false;
      });
    } catch (e) {
      setState(() {
        _error = 'Unable to load dashboard data. Please try again.';
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
      final title = 'Instant Meeting';

      if (authProvider.isPersonal) {
        // Personal users: create a personal meeting directly
        final res = await _api.post('/meetings/personal', body: {
          'title': title,
        });
        if (res.statusCode == 201) {
          final data = json.decode(res.body);
          if (mounted) {
            await _showInviteAndJoin(data);
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
          await _showInviteAndJoin(data);
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
    final titleCtrl = TextEditingController();
    final descCtrl = TextEditingController();

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
                      await _showInviteAndJoin(data);
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
                    await _showInviteAndJoin(data);
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
              auth.userEmail ?? 'Signed in',
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
                  _buildProfileDetailRow(Icons.badge_outlined, 'User ID', auth.currentUser ?? 'Signed in'),
                  const Divider(height: 16),
                  _buildProfileDetailRow(Icons.business_outlined, 'Workspace', auth.currentCompanyId ?? 'Personal'),
                  const Divider(height: 16),
                  _buildProfileDetailRow(Icons.verified_user_outlined, 'Mode', auth.isPersonal ? 'Personal' : 'Workspace'),
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
    final compact = MediaQuery.sizeOf(context).width < 820;

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
                      _buildModernHeader(authProvider),
                      const SizedBox(height: 24),
                      _buildModernActions(),
                      const SizedBox(height: 20),
                      const SizedBox(height: 28),
                      _buildModernContent(),
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
                        Text(
                          authProvider.isPersonal ? 'Personal' : 'Workspace',
                          style: const TextStyle(fontSize: 10, color: Color(0xFFFF5722), fontWeight: FontWeight.w600),
                        ),
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
      {'icon': Icons.present_to_all_rounded, 'title': 'Share Screen', 'sub': 'Available inside a call', 'color': Colors.blue.shade50, 'iconColor': Colors.blue.shade700, 'tap': _startInstantMeeting},
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
                  Expanded(child: _buildCounterTile(Icons.videocam_outlined, '${analytics['meeting_count'] ?? 0}', 'Total Meetings', Colors.orange.shade50, Colors.orange.shade800)),
                  const SizedBox(width: 12),
                  Expanded(child: _buildCounterTile(Icons.description_outlined, '${(analytics['topics'] ?? 0) + (analytics['decisions'] ?? 0)}', 'Notes Generated', Colors.orange.shade50, Colors.orange.shade800)),
                  const SizedBox(width: 12),
                  Expanded(child: _buildCounterTile(Icons.people_outline, '${analytics['attendance'] ?? 0}', 'Attendance Records', Colors.orange.shade50, Colors.orange.shade800)),
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
              // Recent activity from real meeting data
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
                        const Text('Recent Activity', style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold, color: Color(0xFF0F172A))),
                        TextButton(
                          onPressed: () => Navigator.pushNamed(context, AppRouter.meetings),
                          child: const Text('View Meetings ->', style: TextStyle(color: Color(0xFFFF5722), fontWeight: FontWeight.bold, fontSize: 12)),
                        ),
                      ],
                    ),
                    const SizedBox(height: 16),

                    if (_meetingsList.isEmpty)
                      const SizedBox(height: 120, child: UiState.empty('No meeting activity yet.'))
                    else
                      for (final m in _meetingsList.take(3))
                        _buildActivityItem(m),
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
                    Text('- MeetVault', style: TextStyle(fontSize: 12, color: Color(0xFF64748B), fontWeight: FontWeight.w600)),
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
    final desc = m['description'] ?? m['status'] ?? 'Meeting';
    final publicId = m['public_id'];
    final inviteCode = m['invite_code'] ?? publicId ?? '';
    final scheduled = _formatMeetingDate(m['scheduled_start_time']);

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
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
            decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(10)),
            child: Column(
              children: [
                Text(scheduled.$1, style: const TextStyle(fontSize: 12, fontWeight: FontWeight.bold, color: Color(0xFF0F172A))),
                Text(scheduled.$2, style: const TextStyle(fontSize: 10, color: Color(0xFFFF5722), fontWeight: FontWeight.bold)),
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

          FilledButton.icon(
            style: FilledButton.styleFrom(
              backgroundColor: const Color(0xFFFF5722),
              padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
              shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
            ),
            onPressed: inviteCode.toString().isEmpty ? null : () => _joinMeeting(inviteCode.toString()),
            icon: const Icon(Icons.videocam, size: 16),
            label: const Text('Join', style: TextStyle(fontSize: 12, fontWeight: FontWeight.bold)),
          ),
        ],
      ),
    );
  }

  Widget _buildModernHeader(AuthProvider auth) {
    final name = auth.displayName.isEmpty ? 'there' : auth.displayName;
    return LayoutBuilder(builder: (context, constraints) {
      final wide = constraints.maxWidth >= 760;
      final search = SizedBox(
        height: 46,
        child: TextField(
          onSubmitted: (_) => Navigator.pushNamed(context, AppRouter.search),
          decoration: const InputDecoration(
            hintText: 'Search meetings, notes, people',
            prefixIcon: Icon(Icons.search_rounded),
            filled: true,
            fillColor: Colors.white,
            border: OutlineInputBorder(borderSide: BorderSide(color: Color(0xFFDDE4EE))),
            enabledBorder: OutlineInputBorder(borderSide: BorderSide(color: Color(0xFFDDE4EE))),
          ),
        ),
      );
      final profile = OutlinedButton.icon(
        onPressed: () => _showUserProfileDialog(auth),
        icon: CircleAvatar(
          radius: 13,
          backgroundColor: const Color(0xFF0F766E),
          child: Text(name[0].toUpperCase(), style: const TextStyle(color: Colors.white, fontSize: 12, fontWeight: FontWeight.w800)),
        ),
        label: Text(wide ? name : 'Account', overflow: TextOverflow.ellipsis),
      );

      return Container(
        padding: EdgeInsets.all(wide ? 24 : 18),
        decoration: BoxDecoration(
          color: const Color(0xFFFAFBFC),
          borderRadius: BorderRadius.circular(8),
          border: Border.all(color: const Color(0xFFDDE4EE)),
        ),
        child: wide
            ? Row(
                children: [
                  Expanded(
                    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                      Text(auth.isPersonal ? 'Personal command center' : 'Organization command center', style: const TextStyle(color: Color(0xFF536176), fontSize: 13, fontWeight: FontWeight.w700)),
                      const SizedBox(height: 6),
                      Text('MeetVault dashboard', style: const TextStyle(fontSize: 30, fontWeight: FontWeight.w900, color: Color(0xFF111827))),
                      const SizedBox(height: 6),
                      Text('Signed in as $name. Build ${_appBuildSha.length > 7 ? _appBuildSha.substring(0, 7) : _appBuildSha}', style: const TextStyle(color: Color(0xFF64748B), fontSize: 13)),
                    ]),
                  ),
                  SizedBox(width: 360, child: search),
                  const SizedBox(width: 12),
                  profile,
                ],
              )
            : Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(auth.isPersonal ? 'Personal command center' : 'Organization command center', style: const TextStyle(color: Color(0xFF536176), fontSize: 12, fontWeight: FontWeight.w700)),
                  const SizedBox(height: 6),
                  const Text('MeetVault dashboard', style: TextStyle(fontSize: 25, fontWeight: FontWeight.w900, color: Color(0xFF111827))),
                  const SizedBox(height: 6),
                  Text('Build ${_appBuildSha.length > 7 ? _appBuildSha.substring(0, 7) : _appBuildSha}', style: const TextStyle(color: Color(0xFF64748B), fontSize: 12)),
                  const SizedBox(height: 14),
                  search,
                  const SizedBox(height: 12),
                  profile,
                ],
              ),
      );
    });
  }

  Widget _buildModernActions() {
    return LayoutBuilder(builder: (context, constraints) {
      final wide = constraints.maxWidth >= 760;
      final start = Container(
        padding: const EdgeInsets.all(20),
        decoration: BoxDecoration(color: const Color(0xFF111827), borderRadius: BorderRadius.circular(8)),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          const Icon(Icons.video_call_rounded, color: Color(0xFF2DD4BF), size: 32),
          const SizedBox(height: 14),
          const Text('Host instant meeting', style: TextStyle(color: Colors.white, fontSize: 19, fontWeight: FontWeight.w900)),
          const SizedBox(height: 6),
          const Text('Creates a real backend meeting, invite code, and shareable join link.', style: TextStyle(color: Color(0xFFCBD5E1), height: 1.35)),
          const SizedBox(height: 18),
          FilledButton.icon(onPressed: _startInstantMeeting, icon: const Icon(Icons.add_rounded), label: const Text('Create and invite')),
        ]),
      );
      final join = Container(
        padding: const EdgeInsets.all(20),
        decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(8), border: Border.all(color: const Color(0xFFDDE4EE))),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          const Icon(Icons.login_rounded, color: Color(0xFFF97316), size: 30),
          const SizedBox(height: 14),
          const Text('Join with code or link', style: TextStyle(fontSize: 19, fontWeight: FontWeight.w900, color: Color(0xFF111827))),
          const SizedBox(height: 6),
          const Text('Paste MTG code or full invite URL from another device.', style: TextStyle(color: Color(0xFF64748B), height: 1.35)),
          const SizedBox(height: 18),
          Row(children: [
            Expanded(child: TextField(controller: _joinCodeCtrl, textCapitalization: TextCapitalization.characters, onSubmitted: _joinMeeting, decoration: const InputDecoration(hintText: 'MTG-XXXXXX or invite link', prefixIcon: Icon(Icons.tag_rounded)))),
            const SizedBox(width: 8),
            FilledButton(onPressed: () => _joinMeeting(_joinCodeCtrl.text), child: const Text('Join')),
          ]),
        ]),
      );
      return wide ? Row(crossAxisAlignment: CrossAxisAlignment.stretch, children: [Expanded(child: start), const SizedBox(width: 16), Expanded(child: join)]) : Column(children: [start, const SizedBox(height: 12), join]);
    });
  }

  Widget _buildModernContent() {
    final analytics = _analytics ?? {};
    final cards = [
      _buildCounterTile(Icons.videocam_outlined, '${analytics['meeting_count'] ?? 0}', 'Meetings', Colors.teal.shade50, Colors.teal.shade700),
      _buildCounterTile(Icons.description_outlined, '${(analytics['topics'] ?? 0) + (analytics['decisions'] ?? 0)}', 'Notes', Colors.indigo.shade50, Colors.indigo.shade700),
      _buildCounterTile(Icons.people_outline, '${analytics['attendance'] ?? 0}', 'Attendance', Colors.orange.shade50, Colors.orange.shade800),
      _buildCounterTile(Icons.access_time_rounded, '${((analytics['meeting_duration'] ?? 0) / 3600).round()}h', 'Hours', Colors.blueGrey.shade50, Colors.blueGrey.shade700),
    ];

    return LayoutBuilder(builder: (context, constraints) {
      final wide = constraints.maxWidth >= 900;
      final meetings = Container(
        padding: const EdgeInsets.all(20),
        decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(8), border: Border.all(color: const Color(0xFFDDE4EE))),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            const Expanded(child: Text('Live and recent meetings', style: TextStyle(fontSize: 20, fontWeight: FontWeight.w900, color: Color(0xFF111827)))),
            TextButton.icon(onPressed: () => Navigator.pushNamed(context, AppRouter.meetings), icon: const Icon(Icons.arrow_forward_rounded, size: 18), label: const Text('Open meetings')),
          ]),
          const SizedBox(height: 14),
          if (_meetingsList.isEmpty)
            const SizedBox(height: 140, child: UiState.empty('No meetings yet'))
          else
            ..._meetingsList.take(4).map(_buildMeetingCard),
        ]),
      );
      final side = Column(children: [
        Container(
          width: double.infinity,
          padding: const EdgeInsets.all(18),
          decoration: BoxDecoration(color: const Color(0xFFEFF6FF), borderRadius: BorderRadius.circular(8), border: Border.all(color: const Color(0xFFBFDBFE))),
          child: const Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('System status', style: TextStyle(fontSize: 17, fontWeight: FontWeight.w900, color: Color(0xFF111827))),
            SizedBox(height: 12),
            Row(children: [Icon(Icons.check_circle_rounded, color: Color(0xFF0F766E)), SizedBox(width: 8), Expanded(child: Text('Backend API connected'))]),
            SizedBox(height: 8),
            Row(children: [Icon(Icons.key_rounded, color: Color(0xFFF97316)), SizedBox(width: 8), Expanded(child: Text('Invite codes and links enabled'))]),
            SizedBox(height: 8),
            Row(children: [Icon(Icons.devices_rounded, color: Color(0xFF4F46E5)), SizedBox(width: 8), Expanded(child: Text('Responsive desktop and mobile layout'))]),
          ]),
        ),
        const SizedBox(height: 12),
        GridView.count(crossAxisCount: 2, shrinkWrap: true, physics: const NeverScrollableScrollPhysics(), crossAxisSpacing: 10, mainAxisSpacing: 10, childAspectRatio: 1.35, children: cards),
      ]);
      return wide ? Row(crossAxisAlignment: CrossAxisAlignment.start, children: [Expanded(flex: 3, child: meetings), const SizedBox(width: 16), Expanded(flex: 2, child: side)]) : Column(children: [meetings, const SizedBox(height: 14), side]);
    });
  }

  Widget _buildCompactHeader(AuthProvider auth) {
    final name = auth.displayName.isEmpty ? 'there' : auth.displayName;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(children: [
          Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            const Text('Your workspace', style: TextStyle(color: Color(0xFF64748B), fontSize: 13)),
            const SizedBox(height: 4),
            Text('Hi, $name', style: const TextStyle(fontSize: 27, fontWeight: FontWeight.w800, color: Color(0xFF111827))),
          ])),
          IconButton(onPressed: () => _showUserProfileDialog(auth), icon: const Icon(Icons.account_circle_outlined, size: 30)),
        ]),
        const SizedBox(height: 16),
        Container(
          height: 48,
          decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(14), border: Border.all(color: const Color(0xFFE2E8F0))),
          child: TextField(
            onSubmitted: (_) => Navigator.pushNamed(context, AppRouter.search),
            decoration: const InputDecoration(hintText: 'Search meetings or topics', prefixIcon: Icon(Icons.search), border: InputBorder.none),
          ),
        ),
      ],
    );
  }

  Widget _buildCompactActions() {
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      Container(
        padding: const EdgeInsets.all(20),
        decoration: BoxDecoration(color: const Color(0xFF111827), borderRadius: BorderRadius.circular(20)),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          const Icon(Icons.videocam_rounded, color: Color(0xFFF97316), size: 30),
          const SizedBox(height: 12),
          const Text('Ready when you are', style: TextStyle(color: Colors.white, fontSize: 20, fontWeight: FontWeight.w800)),
          const SizedBox(height: 4),
          const Text('Start a room and invite your team in seconds.', style: TextStyle(color: Color(0xFFCBD5E1))),
          const SizedBox(height: 16),
          FilledButton.icon(onPressed: _startInstantMeeting, icon: const Icon(Icons.add), label: const Text('New meeting')),
        ]),
      ),
      const SizedBox(height: 12),
      Row(children: [
        Expanded(child: TextField(controller: _joinCodeCtrl, textCapitalization: TextCapitalization.characters, decoration: const InputDecoration(labelText: 'Meeting code', prefixIcon: Icon(Icons.tag)))),
        const SizedBox(width: 8),
        FilledButton(onPressed: () => _joinMeeting(_joinCodeCtrl.text), child: const Text('Join')),
      ]),
    ]);
  }

  Widget _buildCompactContent() {
    final analytics = _analytics ?? {};
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
        const Text('Your meetings', style: TextStyle(fontSize: 20, fontWeight: FontWeight.w800)),
        TextButton(onPressed: () => Navigator.pushNamed(context, AppRouter.meetings), child: const Text('View all')),
      ]),
      if (_meetingsList.isEmpty) const SizedBox(height: 120, child: UiState.empty('No meetings yet')) else ..._meetingsList.take(3).map(_buildMeetingCard),
      const SizedBox(height: 12),
      GridView.count(crossAxisCount: 2, shrinkWrap: true, physics: const NeverScrollableScrollPhysics(), crossAxisSpacing: 10, mainAxisSpacing: 10, childAspectRatio: 2.1, children: [
        _buildCounterTile(Icons.videocam_outlined, '${analytics['meeting_count'] ?? 0}', 'Meetings', Colors.orange.shade50, Colors.orange.shade800),
        _buildCounterTile(Icons.description_outlined, '${(analytics['topics'] ?? 0) + (analytics['decisions'] ?? 0)}', 'Notes', Colors.teal.shade50, Colors.teal.shade700),
        _buildCounterTile(Icons.people_outline, '${analytics['attendance'] ?? 0}', 'Attendees', Colors.blue.shade50, Colors.blue.shade700),
        _buildCounterTile(Icons.access_time_rounded, '${((analytics['meeting_duration'] ?? 0) / 3600).round()}h', 'Hours', Colors.purple.shade50, Colors.purple.shade700),
      ]),
    ]);
  }

  Future<void> _showInviteAndJoin(Map<String, dynamic> meeting) async {
    if (!mounted) return;
    final code = (meeting['invite_code'] ?? meeting['public_id'] ?? '').toString();
    final authProvider = Provider.of<AuthProvider>(context, listen: false);
    final creatorName = authProvider.user?.fullName ?? authProvider.user?.email ?? 'Host';

    await showDialog<void>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(24)),
        contentPadding: const EdgeInsets.all(24),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                const Expanded(
                  child: Text(
                    "Here's your joining info",
                    style: TextStyle(fontWeight: FontWeight.bold, fontSize: 18, color: Color(0xFF202124)),
                  ),
                ),
                IconButton(
                  icon: const Icon(Icons.close, size: 20, color: Color(0xFF5F6368)),
                  onPressed: () => Navigator.pop(dialogContext),
                  padding: EdgeInsets.zero,
                  constraints: const BoxConstraints(),
                  tooltip: 'Close',
                ),
              ],
            ),
            const SizedBox(height: 8),
            const Text(
              'Send this to people you want to meet with. Be sure to save it so you can use it later, too.',
              style: TextStyle(fontSize: 13, color: Color(0xFF5F6368), height: 1.4),
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
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      const Text('Created by: ', style: TextStyle(fontSize: 13, color: Color(0xFF475569))),
                      Expanded(
                        child: Text(
                          creatorName,
                          style: const TextStyle(fontSize: 13, fontWeight: FontWeight.bold, color: Color(0xFF0F172A)),
                          overflow: TextOverflow.ellipsis,
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 4),
                  const Row(
                    children: [
                      Text('Members: ', style: TextStyle(fontSize: 13, color: Color(0xFF475569))),
                      Text('1 participant (Host)', style: TextStyle(fontSize: 13, fontWeight: FontWeight.bold, color: Color(0xFF0F172A))),
                    ],
                  ),
                ],
              ),
            ),
            const SizedBox(height: 16),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 6),
              decoration: BoxDecoration(
                color: const Color(0xFFF1F3F4),
                borderRadius: BorderRadius.circular(10),
                border: Border.all(color: const Color(0xFFDADCE0)),
              ),
              child: Row(
                children: [
                  Expanded(
                    child: Text(
                      code,
                      style: const TextStyle(
                        fontFamily: 'monospace',
                        fontSize: 16,
                        fontWeight: FontWeight.bold,
                        color: Color(0xFF202124),
                        letterSpacing: 1.1,
                      ),
                    ),
                  ),
                  IconButton(
                    icon: const Icon(Icons.copy_rounded, color: Color(0xFF1A73E8), size: 20),
                    tooltip: 'Copy Code',
                    onPressed: () async {
                      await Clipboard.setData(ClipboardData(text: code));
                      if (dialogContext.mounted) {
                        ScaffoldMessenger.of(dialogContext).showSnackBar(
                          const SnackBar(content: Text('Invite code copied to clipboard')),
                        );
                      }
                    },
                  ),
                ],
              ),
            ),
            const SizedBox(height: 20),
            SizedBox(
              width: double.infinity,
              child: FilledButton(
                style: FilledButton.styleFrom(
                  backgroundColor: const Color(0xFF1A73E8),
                  padding: const EdgeInsets.symmetric(vertical: 12),
                  shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
                ),
                onPressed: () {
                  Navigator.pop(dialogContext);
                  Navigator.pushNamed(context, AppRouter.meetingRoom, arguments: {
                    'id': meeting['public_id'],
                    'title': meeting['title'] ?? 'Meeting Room',
                    'isHost': true,
                  });
                },
                child: const Text('Join Meeting', style: TextStyle(fontSize: 15, fontWeight: FontWeight.bold)),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildActivityItem(Map<String, dynamic> meeting) {
    final title = meeting['title']?.toString() ?? 'Meeting';
    final status = meeting['status']?.toString() ?? 'SCHEDULED';
    return Padding(
      padding: const EdgeInsets.only(bottom: 14),
      child: Row(
        children: [
          Container(
            width: 8,
            height: 8,
            decoration: BoxDecoration(
              color: status == 'LIVE' ? const Color(0xFFFF5722) : const Color(0xFFCBD5E1),
              shape: BoxShape.circle,
            ),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Text(title, style: const TextStyle(fontSize: 13, fontWeight: FontWeight.bold, color: Color(0xFF0F172A))),
          ),
          Text(status, style: const TextStyle(fontSize: 11, color: Color(0xFF64748B), fontWeight: FontWeight.w600)),
        ],
      ),
    );
  }

  (String, String) _formatMeetingDate(dynamic value) {
    if (value == null) return ('Unscheduled', 'Any time');
    final parsed = DateTime.tryParse(value.toString());
    if (parsed == null) return ('Scheduled', 'Soon');
    const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
    final local = parsed.toLocal();
    return ('${months[local.month - 1]} ${local.day}', '${local.hour.toString().padLeft(2, '0')}:${local.minute.toString().padLeft(2, '0')}');
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
