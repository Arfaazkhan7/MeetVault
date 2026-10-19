import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';
import '../../core/navigation/app_router.dart';
import '../../core/providers/auth_provider.dart';
import '../../core/services/api_service.dart';
import '../../core/widgets/enterprise_scaffold.dart';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

String _formatDate(String? iso) {
  if (iso == null || iso.isEmpty) return '—';
  try {
    final dt = DateTime.parse(iso).toLocal();
    const months = [
      'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
      'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
    ];
    final month = months[dt.month - 1];
    final day = dt.day.toString().padLeft(2, '0');
    final hour = dt.hour.toString().padLeft(2, '0');
    final minute = dt.minute.toString().padLeft(2, '0');
    return '$month $day, ${dt.year} – $hour:$minute';
  } catch (_) {
    return iso;
  }
}

// ---------------------------------------------------------------------------
// Screen
// ---------------------------------------------------------------------------

class MeetingsScreen extends StatefulWidget {
  const MeetingsScreen({super.key});

  @override
  State<MeetingsScreen> createState() => _MeetingsScreenState();
}

class _MeetingsScreenState extends State<MeetingsScreen> {
  static const _primaryBlue = Color(0xFF2563EB);
  static const _success = Color(0xFF10B981);
  static const _errorRed = Color(0xFFEF4444);

  bool _loading = true;
  String? _error;

  List<Map<String, dynamic>> _all = [];

  String _search = '';
  String _statusFilter = 'All';

  final _searchCtrl = TextEditingController();

  static const _statuses = ['All', 'SCHEDULED', 'LIVE', 'COMPLETED', 'CANCELLED'];

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _searchCtrl.dispose();
    super.dispose();
  }

  // -------------------------------------------------------------------------
  // Data loading
  // -------------------------------------------------------------------------

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final api = ApiService();
      final List<Map<String, dynamic>> allMeetings = [];

      final histResp = await api.get('/meetings/history');
      if (histResp.statusCode == 200) {
        final dynamic decoded = json.decode(histResp.body);
        if (decoded is List) {
          for (final item in decoded) {
            if (item is! Map<String, dynamic>) continue;
            final meetingId = (item['meeting_id'] ?? item['public_id'] ?? '').toString();
            final role = (item['my_role'] ?? item['role'] ?? 'ATTENDEE').toString();
            final participants = (item['participants'] as List?) ?? [];
            final transStatus = (item['transcription_status'] ?? 'pending').toString();
            allMeetings.add({
              'public_id': meetingId,
              'meeting_id': meetingId,
              'title': item['title'] ?? 'Untitled Meeting',
              'description': item['description'],
              'invite_code': item['meeting_code'] ?? item['invite_code'],
              'meeting_type': item['meeting_type'] ?? 'PERSONAL',
              'scheduled_start_time': item['started_at'] ?? item['scheduled_start_time'],
              'started_at': item['started_at'],
              'ended_at': item['ended_at'],
              'duration_seconds': item['duration_seconds'],
              'role': role,
              'my_role': role,
              'status': (item['status'] ?? 'COMPLETED').toString(),
              'transcription_status': transStatus,
              'transcription_error': item['transcription_error'],
              'recording_url': item['recording_url'],
              'participants': participants,
              'participant_count': participants.length,
              'project_name': role.toUpperCase() == 'HOST' ? 'Host' : 'Attendee',
            });
          }
        }
      } else if (histResp.statusCode == 401) {
        throw Exception('Session expired. Please sign in again.');
      } else if (histResp.statusCode == 403) {
        throw Exception('Access denied: You do not have permission to view meeting history.');
      } else {
        throw Exception('Failed to load meeting history (${histResp.statusCode}).');
      }

      allMeetings.sort((a, b) {
        final aTime = a['started_at']?.toString() ?? a['scheduled_start_time']?.toString() ?? '';
        final bTime = b['started_at']?.toString() ?? b['scheduled_start_time']?.toString() ?? '';
        return bTime.compareTo(aTime);
      });

      if (!mounted) return;
      setState(() {
        _all = allMeetings;
        _loading = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = e.toString().replaceFirst('Exception: ', '');
        _loading = false;
      });
    }
  }

  // -------------------------------------------------------------------------
  // Filtering
  // -------------------------------------------------------------------------

  List<Map<String, dynamic>> get _filtered {
    return _all.where((m) {
      final title = (m['title'] ?? '').toString().toLowerCase();
      final project = (m['project_name'] ?? '').toString().toLowerCase();
      final matchSearch = _search.isEmpty ||
          title.contains(_search.toLowerCase()) ||
          project.contains(_search.toLowerCase());
      final status = (m['status'] ?? '').toString().toUpperCase();
      final matchStatus = _statusFilter == 'All' || status == _statusFilter;
      return matchSearch && matchStatus;
    }).toList();
  }

  // -------------------------------------------------------------------------
  // Status badge
  // -------------------------------------------------------------------------

  Color _statusColor(String status) {
    switch (status.toUpperCase()) {
      case 'SCHEDULED':
        return _primaryBlue;
      case 'LIVE':
        return _success;
      case 'COMPLETED':
        return Colors.grey;
      case 'CANCELLED':
        return _errorRed;
      default:
        return const Color(0xFFF59E0B);
    }
  }

  Widget _statusBadge(String status) {
    final color = _statusColor(status);
    final isLive = status.toUpperCase() == 'LIVE';
    final chip = Chip(
      label: Text(
        status.toUpperCase(),
        style: const TextStyle(
            color: Colors.white, fontSize: 11, fontWeight: FontWeight.w600),
      ),
      backgroundColor: color,
      padding: const EdgeInsets.symmetric(horizontal: 2),
      materialTapTargetSize: MaterialTapTargetSize.shrinkWrap,
      visualDensity: VisualDensity.compact,
    );
    if (!isLive) return chip;
    return _PulsingChip(child: chip);
  }

  // -------------------------------------------------------------------------
  // Schedule Meeting dialog
  // -------------------------------------------------------------------------

  Future<void> _showScheduleDialog() async {
    final authProvider = Provider.of<AuthProvider>(context, listen: false);

    if (authProvider.isPersonal) {
      // Personal users: simple title dialog → POST /meetings/personal
      final titleCtrl = TextEditingController();
      final api = ApiService();
      await showDialog<void>(
        context: context,
        builder: (ctx) => AlertDialog(
          title: const Text('Schedule Meeting'),
          content: TextField(
            controller: titleCtrl,
            autofocus: true,
            decoration: const InputDecoration(
              labelText: 'Meeting Title',
              hintText: 'e.g. Weekly Sync',
              border: OutlineInputBorder(),
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(ctx),
              child: const Text('Cancel'),
            ),
            FilledButton(
              onPressed: () async {
                final title = titleCtrl.text.trim();
                if (title.isEmpty) return;
                Navigator.pop(ctx);
                try {
                  final res = await api.post('/meetings/personal', body: {'title': title});
                  if (res.statusCode == 201 && mounted) {
                    final data = json.decode(res.body);
                    await _showCreatedMeetingModal(data);
                    _load();
                  }
                } catch (e) {
                  if (mounted) {
                    ScaffoldMessenger.of(context).showSnackBar(
                      SnackBar(content: Text('Failed to create meeting: $e')),
                    );
                  }
                }
              },
              child: const Text('Create'),
            ),
          ],
        ),
      );
      return;
    }

    // Org users: collect unique projects from loaded meetings list
    final projectMap = <String, String>{};
    for (final m in _all) {
      final name = m['project_name']?.toString() ?? '';
      final id = (m['project_public_id'] ?? m['project_id'] ?? '').toString();
      if (id.isNotEmpty && name.isNotEmpty) projectMap[id] = name;
    }

    if (projectMap.isEmpty) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
            content: Text('No projects found. Please create a project first.')),
      );
      return;
    }

    String? selectedId = projectMap.keys.first;

    await showDialog<void>(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setDlg) => AlertDialog(
          title: const Text('Schedule Meeting'),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text('Select a project for the new meeting:'),
              const SizedBox(height: 12),
              DropdownButtonFormField<String>(
                value: selectedId,
                isExpanded: true,
                decoration: const InputDecoration(
                  border: OutlineInputBorder(),
                  contentPadding:
                      EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                ),
                items: projectMap.entries
                    .map((e) => DropdownMenuItem(
                          value: e.key,
                          child: Text(e.value, overflow: TextOverflow.ellipsis),
                        ))
                    .toList(),
                onChanged: (v) => setDlg(() => selectedId = v),
              ),
            ],
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(ctx),
              child: const Text('Cancel'),
            ),
            FilledButton(
              onPressed: () {
                Navigator.pop(ctx);
                if (selectedId != null && mounted) {
                  Navigator.pushNamed(
                    context,
                    AppRouter.meetingDetails,
                    arguments: {'id': selectedId, 'create': true},
                  );
                }
              },
              child: const Text('Continue'),
            ),
          ],
        ),
      ),
    );
  }

  Future<void> _showCreatedMeetingModal(Map<String, dynamic> meeting) async {
    if (!mounted) return;
    final code = (meeting['invite_code'] ?? meeting['public_id'] ?? '').toString();
    final authProvider = Provider.of<AuthProvider>(context, listen: false);
    final creatorName = authProvider.displayName;

    await showDialog<void>(
      context: context,
      builder: (dialogCtx) => AlertDialog(
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
                  onPressed: () => Navigator.pop(dialogCtx),
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
                      if (dialogCtx.mounted) {
                        ScaffoldMessenger.of(dialogCtx).showSnackBar(
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
                  Navigator.pop(dialogCtx);
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

  // -------------------------------------------------------------------------
  // Build
  // -------------------------------------------------------------------------

  @override
  Widget build(BuildContext context) {
    return EnterpriseScaffold(
      title: 'Meetings',
      currentRoute: AppRouter.meetings,
      floatingActionButton: FloatingActionButton.extended(
        onPressed: _showScheduleDialog,
        icon: const Icon(Icons.add),
        label: const Text('Schedule Meeting'),
      ),
      child: _buildBody(),
    );
  }

  Widget _buildBody() {
    if (_loading) {
      return const Center(child: CircularProgressIndicator());
    }
    if (_error != null) {
      return UiState.error(_error!, onRetry: _load);
    }

    final filtered = _filtered;

    return Column(
      children: [
        _buildSearchAndFilters(),
        Expanded(
          child: RefreshIndicator(
            onRefresh: _load,
            child: filtered.isEmpty
                ? ListView(
                    children: [
                      SizedBox(
                        height: 400,
                        child: UiState.empty(
                          _search.isNotEmpty || _statusFilter != 'All'
                              ? 'No meetings match the current filters.'
                              : 'No meetings found. Schedule one to get started.',
                        ),
                      ),
                    ],
                  )
                : ListView.builder(
                    padding: const EdgeInsets.fromLTRB(16, 8, 16, 100),
                    itemCount: filtered.length,
                    itemBuilder: (ctx, i) => _MeetingCard(
                      meeting: filtered[i],
                      statusBadge: _statusBadge(
                          (filtered[i]['status'] ?? 'UNKNOWN').toString()),
                      onTap: () {
                        final mid = (filtered[i]['public_id'] ?? filtered[i]['meeting_id'] ?? '').toString();
                        final title = (filtered[i]['title'] ?? 'Untitled Meeting').toString();
                        Navigator.pushNamed(
                          ctx,
                          AppRouter.meetingDetails,
                          arguments: {'id': mid, 'title': title},
                        );
                      },
                    ),
                  ),
          ),
        ),
      ],
    );
  }

  Widget _buildSearchAndFilters() {
    return Container(
      color: Theme.of(context).colorScheme.surface,
      padding: const EdgeInsets.fromLTRB(16, 12, 16, 8),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          TextField(
            controller: _searchCtrl,
            decoration: InputDecoration(
              hintText: 'Search meetings or projects…',
              prefixIcon: const Icon(Icons.search),
              suffixIcon: _search.isNotEmpty
                  ? IconButton(
                      icon: const Icon(Icons.clear),
                      onPressed: () {
                        _searchCtrl.clear();
                        setState(() => _search = '');
                      },
                    )
                  : null,
              border: OutlineInputBorder(
                borderRadius: BorderRadius.circular(10),
              ),
              contentPadding:
                  const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
              isDense: true,
            ),
            onChanged: (v) => setState(() => _search = v),
          ),
          const SizedBox(height: 10),
          SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            child: Row(
              children: _statuses.map((s) {
                final selected = _statusFilter == s;
                return Padding(
                  padding: const EdgeInsets.only(right: 8),
                  child: FilterChip(
                    label: Text(s),
                    selected: selected,
                    onSelected: (_) => setState(() => _statusFilter = s),
                    selectedColor: _statusColor(s).withOpacity(0.15),
                    checkmarkColor: _statusColor(s),
                    labelStyle: TextStyle(
                      color: selected ? _statusColor(s) : null,
                      fontWeight:
                          selected ? FontWeight.w600 : FontWeight.normal,
                    ),
                  ),
                );
              }).toList(),
            ),
          ),
        ],
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Meeting card
// ---------------------------------------------------------------------------

String _formatDuration(dynamic sec) {
  if (sec == null) return '0 min';
  final seconds = sec is int ? sec : int.tryParse(sec.toString()) ?? 0;
  if (seconds <= 0) return '0 min';
  final mins = seconds ~/ 60;
  if (mins < 60) return '$mins min';
  final hrs = mins ~/ 60;
  final rMins = mins % 60;
  return '${hrs}h ${rMins}m';
}

class _MeetingCard extends StatelessWidget {
  final Map<String, dynamic> meeting;
  final Widget statusBadge;
  final VoidCallback onTap;

  const _MeetingCard({
    required this.meeting,
    required this.statusBadge,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    final title = meeting['title']?.toString() ?? 'Untitled Meeting';
    final startTime = _formatDate(meeting['scheduled_start_time']?.toString() ?? meeting['started_at']?.toString());
    final code = meeting['invite_code']?.toString() ?? meeting['meeting_code']?.toString() ?? '—';
    final role = meeting['role']?.toString() ?? 'PARTICIPANT';
    final durationStr = _formatDuration(meeting['duration_seconds']);

    final participants = (meeting['participants'] as List?) ?? [];
    final participantNames = participants.isNotEmpty
        ? participants.map((p) => (p['name'] ?? p['email'] ?? 'User').toString()).join(', ')
        : '${meeting['participant_count'] ?? 1} participant(s)';

    final transStatus = (meeting['transcription_status'] ?? '').toString().toLowerCase();

    Widget? transcriptionBadge;
    if (transStatus == 'completed') {
      transcriptionBadge = Container(
        padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 2.5),
        decoration: BoxDecoration(
          color: const Color(0xFFF0FDF4),
          borderRadius: BorderRadius.circular(6),
          border: Border.all(color: const Color(0xFF86EFAC)),
        ),
        child: const Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.description, size: 12, color: Color(0xFF15803D)),
            SizedBox(width: 4),
            Text(
              'Transcript Ready',
              style: TextStyle(
                fontSize: 11,
                fontWeight: FontWeight.w600,
                color: Color(0xFF15803D),
              ),
            ),
          ],
        ),
      );
    } else if (transStatus == 'processing' || transStatus == 'queued') {
      transcriptionBadge = Container(
        padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 2.5),
        decoration: BoxDecoration(
          color: const Color(0xFFFFFBEB),
          borderRadius: BorderRadius.circular(6),
          border: Border.all(color: const Color(0xFFFDE68A)),
        ),
        child: const Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            SizedBox(
              width: 10,
              height: 10,
              child: CircularProgressIndicator(strokeWidth: 1.5, color: Color(0xFFB45309)),
            ),
            SizedBox(width: 4),
            Text(
              'Transcribing...',
              style: TextStyle(
                fontSize: 11,
                fontWeight: FontWeight.w600,
                color: Color(0xFFB45309),
              ),
            ),
          ],
        ),
      );
    } else if (transStatus == 'failed') {
      transcriptionBadge = Container(
        padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 2.5),
        decoration: BoxDecoration(
          color: const Color(0xFFFEF2F2),
          borderRadius: BorderRadius.circular(6),
          border: Border.all(color: const Color(0xFFFECACA)),
        ),
        child: const Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.error_outline, size: 12, color: Color(0xFFB91C1C)),
            SizedBox(width: 4),
            Text(
              'Transcript Failed',
              style: TextStyle(
                fontSize: 11,
                fontWeight: FontWeight.w600,
                color: Color(0xFFB91C1C),
              ),
            ),
          ],
        ),
      );
    }

    return Card(
      margin: const EdgeInsets.only(bottom: 12),
      clipBehavior: Clip.antiAlias,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
      child: InkWell(
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Expanded(
                    child: Text(
                      title,
                      style: const TextStyle(fontSize: 16, fontWeight: FontWeight.bold, color: Color(0xFF0F172A)),
                    ),
                  ),
                  const SizedBox(width: 8),
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                    decoration: BoxDecoration(
                      color: role.toUpperCase() == 'HOST' ? const Color(0xFFEEF2FF) : const Color(0xFFF0FDF4),
                      borderRadius: BorderRadius.circular(6),
                      border: Border.all(color: role.toUpperCase() == 'HOST' ? const Color(0xFFC7D2FE) : const Color(0xFFBBF7D0)),
                    ),
                    child: Text(
                      role.toUpperCase(),
                      style: TextStyle(
                        fontSize: 11,
                        fontWeight: FontWeight.bold,
                        color: role.toUpperCase() == 'HOST' ? const Color(0xFF3730A3) : const Color(0xFF166534),
                      ),
                    ),
                  ),
                  const SizedBox(width: 6),
                  statusBadge,
                ],
              ),
              const SizedBox(height: 10),
              Row(
                children: [
                  const Icon(Icons.schedule, size: 14, color: Color(0xFF64748B)),
                  const SizedBox(width: 6),
                  Text(startTime, style: const TextStyle(fontSize: 13, color: Color(0xFF64748B))),
                  const SizedBox(width: 12),
                  const Icon(Icons.timer_outlined, size: 14, color: Color(0xFF64748B)),
                  const SizedBox(width: 4),
                  Text(durationStr, style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w600, color: Color(0xFF64748B))),
                  const Spacer(),
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                    decoration: BoxDecoration(color: const Color(0xFFF1F5F9), borderRadius: BorderRadius.circular(4)),
                    child: Text(code, style: const TextStyle(fontFamily: 'monospace', fontSize: 12, fontWeight: FontWeight.bold, color: Color(0xFF2563EB))),
                  ),
                ],
              ),
              if (transcriptionBadge != null) ...[
                const SizedBox(height: 8),
                transcriptionBadge,
              ],
              const SizedBox(height: 8),
              Row(
                children: [
                  const Icon(Icons.people_outline, size: 14, color: Color(0xFF64748B)),
                  const SizedBox(width: 6),
                  Expanded(
                    child: Text(
                      'Participants: $participantNames',
                      style: const TextStyle(fontSize: 13, color: Color(0xFF475569)),
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                    ),
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Pulsing animation for LIVE chip
// ---------------------------------------------------------------------------

class _PulsingChip extends StatefulWidget {
  final Widget child;
  const _PulsingChip({required this.child});

  @override
  State<_PulsingChip> createState() => _PulsingChipState();
}

class _PulsingChipState extends State<_PulsingChip>
    with SingleTickerProviderStateMixin {
  late final AnimationController _ctrl;
  late final Animation<double> _opacity;

  @override
  void initState() {
    super.initState();
    _ctrl = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 900),
    )..repeat(reverse: true);
    _opacity = Tween<double>(begin: 0.5, end: 1.0).animate(_ctrl);
  }

  @override
  void dispose() {
    _ctrl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) =>
      FadeTransition(opacity: _opacity, child: widget.child);
}
