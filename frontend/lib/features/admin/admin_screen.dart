import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import '../../core/services/api_service.dart';
import '../../core/navigation/app_router.dart';

class AdminDashboardScreen extends StatefulWidget {
  const AdminDashboardScreen({super.key});

  @override
  State<AdminDashboardScreen> createState() => _AdminDashboardScreenState();
}

class _AdminDashboardScreenState extends State<AdminDashboardScreen> {
  final ApiService _api = ApiService();
  Map<String, dynamic>? _stats;
  List<dynamic> _workspaces = [];
  bool _loading = true;
  String? _error;

  // Create workspace form
  final _orgNameCtrl = TextEditingController();
  final _adminNameCtrl = TextEditingController();
  final _adminEmailCtrl = TextEditingController();
  final _adminPassCtrl = TextEditingController();
  bool _creating = false;
  String? _createError;
  Map<String, dynamic>? _createdWorkspace;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _orgNameCtrl.dispose();
    _adminNameCtrl.dispose();
    _adminEmailCtrl.dispose();
    _adminPassCtrl.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    setState(() { _loading = true; _error = null; });
    try {
      final statsRes = await _api.get('/admin/stats');
      final workspacesRes = await _api.get('/admin/workspaces');
      if (statsRes.statusCode == 200 && workspacesRes.statusCode == 200) {
        setState(() {
          _stats = json.decode(statsRes.body);
          _workspaces = json.decode(workspacesRes.body);
        });
      } else if (statsRes.statusCode == 403) {
        setState(() { _error = 'Access denied. Please log in as System Admin.'; });
        Future.delayed(const Duration(seconds: 2), () {
          if (mounted) Navigator.pushReplacementNamed(context, AppRouter.adminLogin);
        });
      } else {
        setState(() { _error = 'Failed to load admin data'; });
      }
    } catch (e) {
      setState(() { _error = e.toString(); });
    } finally {
      setState(() { _loading = false; });
    }
  }

  Future<void> _createWorkspace() async {
    if (_orgNameCtrl.text.trim().isEmpty || _adminEmailCtrl.text.trim().isEmpty || _adminPassCtrl.text.isEmpty) {
      setState(() { _createError = 'Organization name, admin email and password are required'; });
      return;
    }
    setState(() { _creating = true; _createError = null; _createdWorkspace = null; });
    try {
      final res = await _api.post('/admin/workspaces', body: {
        'organization_name': _orgNameCtrl.text.trim(),
        'admin_name': _adminNameCtrl.text.trim().isEmpty ? 'Admin' : _adminNameCtrl.text.trim(),
        'admin_email': _adminEmailCtrl.text.trim(),
        'admin_password': _adminPassCtrl.text,
      });
      if (res.statusCode == 201) {
        final data = json.decode(res.body);
        setState(() { _createdWorkspace = data; });
        _orgNameCtrl.clear();
        _adminNameCtrl.clear();
        _adminEmailCtrl.clear();
        _adminPassCtrl.clear();
        _load(); // Reload workspaces list
      } else {
        final body = json.decode(res.body);
        setState(() { _createError = body['detail'] ?? 'Failed to create workspace'; });
      }
    } catch (e) {
      setState(() { _createError = e.toString(); });
    } finally {
      setState(() { _creating = false; });
    }
  }

  void _logout() async {
    await _api.clearToken();
    if (mounted) Navigator.pushReplacementNamed(context, AppRouter.adminLogin);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFF0F172A),
      appBar: AppBar(
        backgroundColor: const Color(0xFF1E293B),
        foregroundColor: Colors.white,
        title: Row(
          children: [
            Container(
              width: 32, height: 32,
              decoration: BoxDecoration(
                gradient: const LinearGradient(colors: [Color(0xFF7C3AED), Color(0xFF4F46E5)]),
                borderRadius: BorderRadius.circular(8),
              ),
              child: const Icon(Icons.shield_rounded, color: Colors.white, size: 18),
            ),
            const SizedBox(width: 12),
            const Text('MeetVault Admin', style: TextStyle(fontSize: 18, fontWeight: FontWeight.w700)),
            const SizedBox(width: 8),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
              decoration: BoxDecoration(
                color: const Color(0xFF7C3AED).withOpacity(0.2),
                borderRadius: BorderRadius.circular(4),
                border: Border.all(color: const Color(0xFF7C3AED).withOpacity(0.4)),
              ),
              child: const Text('SYSTEM ADMIN', style: TextStyle(color: Color(0xFF7C3AED), fontSize: 10, fontWeight: FontWeight.w700, letterSpacing: 1)),
            ),
          ],
        ),
        actions: [
          IconButton(icon: const Icon(Icons.refresh), onPressed: _load, tooltip: 'Refresh'),
          IconButton(icon: const Icon(Icons.logout), onPressed: _logout, tooltip: 'Sign Out'),
          const SizedBox(width: 8),
        ],
      ),
      body: _loading
        ? const Center(child: CircularProgressIndicator(color: Color(0xFF7C3AED)))
        : _error != null
          ? Center(child: Text(_error!, style: const TextStyle(color: Color(0xFFEF4444))))
          : SingleChildScrollView(
              padding: const EdgeInsets.all(24),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  // Stats Row
                  _buildSectionTitle('System Overview'),
                  const SizedBox(height: 16),
                  _buildStatsGrid(),
                  const SizedBox(height: 32),

                  // Create Workspace
                  _buildSectionTitle('Create New Workspace'),
                  const SizedBox(height: 16),
                  _buildCreateWorkspaceForm(),
                  const SizedBox(height: 32),

                  // Workspaces List
                  _buildSectionTitle('All Workspaces (${_workspaces.length})'),
                  const SizedBox(height: 16),
                  _buildWorkspacesList(),
                ],
              ),
            ),
    );
  }

  Widget _buildSectionTitle(String title) {
    return Text(title, style: const TextStyle(color: Colors.white, fontSize: 18, fontWeight: FontWeight.w700));
  }

  Widget _buildStatsGrid() {
    final stats = _stats ?? {};
    final items = [
      ('Total Users', stats['total_users']?.toString() ?? '0', Icons.people_rounded, const Color(0xFF3B82F6)),
      ('Workspaces', stats['total_workspaces']?.toString() ?? '0', Icons.business_rounded, const Color(0xFF7C3AED)),
      ('Projects', stats['total_projects']?.toString() ?? '0', Icons.folder_rounded, const Color(0xFF10B981)),
      ('Meetings', stats['total_meetings']?.toString() ?? '0', Icons.video_call_rounded, const Color(0xFFF59E0B)),
      ('Recordings', stats['total_recordings']?.toString() ?? '0', Icons.mic_rounded, const Color(0xFFEF4444)),
    ];
    return Wrap(
      spacing: 16, runSpacing: 16,
      children: items.map((item) => _buildStatCard(item.$1, item.$2, item.$3, item.$4)).toList(),
    );
  }

  Widget _buildStatCard(String label, String value, IconData icon, Color color) {
    return Container(
      width: 160,
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        color: const Color(0xFF1E293B),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: const Color(0xFF334155)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icon, color: color, size: 28),
          const SizedBox(height: 12),
          Text(value, style: TextStyle(color: color, fontSize: 28, fontWeight: FontWeight.w800)),
          const SizedBox(height: 4),
          Text(label, style: const TextStyle(color: Color(0xFF64748B), fontSize: 13)),
        ],
      ),
    );
  }

  Widget _buildCreateWorkspaceForm() {
    return Container(
      padding: const EdgeInsets.all(24),
      decoration: BoxDecoration(
        color: const Color(0xFF1E293B),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: const Color(0xFF334155)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (_createdWorkspace != null) ...[
            _buildSuccessBanner(),
            const SizedBox(height: 20),
          ],
          if (_createError != null) ...[
            Container(
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: const Color(0xFF7F1D1D).withOpacity(0.3),
                borderRadius: BorderRadius.circular(8),
                border: Border.all(color: const Color(0xFFEF4444).withOpacity(0.5)),
              ),
              child: Text(_createError!, style: const TextStyle(color: Color(0xFFEF4444), fontSize: 13)),
            ),
            const SizedBox(height: 16),
          ],
          LayoutBuilder(builder: (context, constraints) {
            final isWide = constraints.maxWidth > 600;
            final fields = [
              _buildField('Organization Name *', 'Acme Corp', _orgNameCtrl, Icons.business_outlined),
              _buildField('Admin Full Name', 'John Admin', _adminNameCtrl, Icons.person_outlined),
              _buildField('Admin Email *', 'admin@acme.com', _adminEmailCtrl, Icons.email_outlined, keyboardType: TextInputType.emailAddress),
              _buildField('Admin Password *', '••••••••••', _adminPassCtrl, Icons.lock_outlined, obscure: true),
            ];
            return isWide
              ? Column(children: [
                  Row(children: [Expanded(child: fields[0]), const SizedBox(width: 16), Expanded(child: fields[1])]),
                  const SizedBox(height: 16),
                  Row(children: [Expanded(child: fields[2]), const SizedBox(width: 16), Expanded(child: fields[3])]),
                ])
              : Column(children: [fields[0], const SizedBox(height: 16), fields[1], const SizedBox(height: 16), fields[2], const SizedBox(height: 16), fields[3]]);
          }),
          const SizedBox(height: 20),
          SizedBox(
            height: 48,
            child: FilledButton.icon(
              onPressed: _creating ? null : _createWorkspace,
              style: FilledButton.styleFrom(
                backgroundColor: const Color(0xFF7C3AED),
                shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
              ),
              icon: _creating ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white)) : const Icon(Icons.add_business_rounded),
              label: Text(_creating ? 'Creating...' : 'Create Workspace'),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildSuccessBanner() {
    final ws = _createdWorkspace!;
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: const Color(0xFF064E3B).withOpacity(0.4),
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: const Color(0xFF10B981).withOpacity(0.5)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Row(children: [
            Icon(Icons.check_circle_rounded, color: Color(0xFF10B981), size: 20),
            SizedBox(width: 8),
            Text('Workspace Created Successfully!', style: TextStyle(color: Color(0xFF10B981), fontWeight: FontWeight.w700)),
          ]),
          const SizedBox(height: 12),
          _buildCredRow('Organization', ws['organization_name'] ?? ''),
          _buildCredRow('Workspace Code', ws['workspace_code'] ?? '', copyable: true),
          _buildCredRow('Admin Email', ws['admin_email'] ?? '', copyable: true),
          _buildCredRow('Workspace ID', ws['workspace_id'] ?? ''),
          Container(
            margin: const EdgeInsets.only(top: 10),
            padding: const EdgeInsets.all(10),
            decoration: BoxDecoration(
              color: Colors.black.withOpacity(0.3),
              borderRadius: BorderRadius.circular(6),
            ),
            child: const Text(
              '⚠️ Share the Workspace Code with your team members. They will need it to join this workspace.',
              style: TextStyle(color: Color(0xFFFBBF24), fontSize: 12),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildCredRow(String label, String value, {bool copyable = false}) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 3),
      child: Row(
        children: [
          SizedBox(width: 120, child: Text('$label:', style: const TextStyle(color: Color(0xFF94A3B8), fontSize: 13))),
          Text(value, style: const TextStyle(color: Colors.white, fontSize: 13, fontWeight: FontWeight.w600)),
          if (copyable) ...[
            const SizedBox(width: 8),
            InkWell(
              onTap: () => Clipboard.setData(ClipboardData(text: value)),
              child: const Icon(Icons.copy_rounded, size: 14, color: Color(0xFF64748B)),
            ),
          ],
        ],
      ),
    );
  }

  Widget _buildField(String label, String hint, TextEditingController ctrl, IconData icon, {bool obscure = false, TextInputType? keyboardType}) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(label, style: const TextStyle(color: Color(0xFF94A3B8), fontSize: 13, fontWeight: FontWeight.w500)),
        const SizedBox(height: 8),
        TextField(
          controller: ctrl,
          obscureText: obscure,
          keyboardType: keyboardType,
          style: const TextStyle(color: Colors.white, fontSize: 14),
          decoration: InputDecoration(
            hintText: hint,
            hintStyle: const TextStyle(color: Color(0xFF475569)),
            prefixIcon: Icon(icon, color: const Color(0xFF475569), size: 18),
            filled: true,
            fillColor: const Color(0xFF0F172A),
            enabledBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(8), borderSide: const BorderSide(color: Color(0xFF334155))),
            focusedBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(8), borderSide: const BorderSide(color: Color(0xFF7C3AED), width: 2)),
          ),
        ),
      ],
    );
  }

  Widget _buildWorkspacesList() {
    if (_workspaces.isEmpty) {
      return Container(
        padding: const EdgeInsets.all(32),
        decoration: BoxDecoration(
          color: const Color(0xFF1E293B),
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: const Color(0xFF334155)),
        ),
        child: const Center(child: Text('No workspaces created yet.', style: TextStyle(color: Color(0xFF64748B)))),
      );
    }
    return Container(
      decoration: BoxDecoration(
        color: const Color(0xFF1E293B),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: const Color(0xFF334155)),
      ),
      child: Column(
        children: _workspaces.asMap().entries.map((entry) {
          final i = entry.key;
          final ws = entry.value;
          return Container(
            padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 16),
            decoration: BoxDecoration(
              border: i < _workspaces.length - 1 ? const Border(bottom: BorderSide(color: Color(0xFF334155))) : null,
            ),
            child: Row(
              children: [
                Container(
                  width: 44, height: 44,
                  decoration: BoxDecoration(
                    color: const Color(0xFF7C3AED).withOpacity(0.15),
                    borderRadius: BorderRadius.circular(10),
                  ),
                  child: const Icon(Icons.business_rounded, color: Color(0xFF7C3AED), size: 22),
                ),
                const SizedBox(width: 16),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(ws['name'] ?? '', style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w600, fontSize: 15)),
                      const SizedBox(height: 4),
                      Row(children: [
                        _buildBadge(ws['workspace_code'] ?? '', const Color(0xFF7C3AED)),
                        const SizedBox(width: 8),
                        _buildBadge('${ws['member_count'] ?? 0} members', const Color(0xFF3B82F6)),
                        const SizedBox(width: 8),
                        _buildBadge('${ws['project_count'] ?? 0} projects', const Color(0xFF10B981)),
                      ]),
                    ],
                  ),
                ),
                IconButton(
                  icon: const Icon(Icons.copy_rounded, size: 18, color: Color(0xFF64748B)),
                  tooltip: 'Copy workspace code',
                  onPressed: () {
                    Clipboard.setData(ClipboardData(text: ws['workspace_code'] ?? ''));
                    ScaffoldMessenger.of(context).showSnackBar(
                      SnackBar(content: Text('Copied: ${ws['workspace_code']}'), duration: const Duration(seconds: 2)),
                    );
                  },
                ),
              ],
            ),
          );
        }).toList(),
      ),
    );
  }

  Widget _buildBadge(String text, Color color) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
      decoration: BoxDecoration(
        color: color.withOpacity(0.15),
        borderRadius: BorderRadius.circular(4),
        border: Border.all(color: color.withOpacity(0.3)),
      ),
      child: Text(text, style: TextStyle(color: color, fontSize: 11, fontWeight: FontWeight.w600)),
    );
  }
}
