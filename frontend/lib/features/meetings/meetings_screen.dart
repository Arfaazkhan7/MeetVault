import 'dart:convert';
import 'package:flutter/material.dart';
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
      final authProvider = Provider.of<AuthProvider>(context, listen: false);

      final List<Map<String, dynamic>> allMeetings = [];

      if (authProvider.isPersonal) {
        // Personal users: fetch personal meetings directly
        try {
          final meetResp = await api.get('/meetings/personal');
          if (meetResp.statusCode == 200) {
            final meetings = List<Map<String, dynamic>>.from(
              json.decode(meetResp.body) as List,
            );
            for (final m in meetings) {
              allMeetings.add({...m, 'project_name': 'Personal'});
            }
          }
        } catch (_) {}
      } else {
        // Org users: fetch via company loop
        final compResp = await api.get('/companies');
        final companies = List<Map<String, dynamic>>.from(
          json.decode(compResp.body) as List,
        );

        for (final company in companies) {
          final compId = company['public_id'] ?? company['id'];
          if (compId == null) continue;

          try {
            final meetResp = await api.get('/companies/$compId/meetings');
            final meetings = List<Map<String, dynamic>>.from(
              json.decode(meetResp.body) as List,
            );
            for (final m in meetings) {
              allMeetings.add({...m, 'project_name': m['project_id'] ?? 'General'});
            }
          } catch (_) {
            // skip unavailable companies
          }
        }
      }

      allMeetings.sort((a, b) {
        final aTime = a['scheduled_start_time'] as String? ?? '';
        final bTime = b['scheduled_start_time'] as String? ?? '';
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
        _error = e.toString();
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
                    Navigator.pushNamed(
                      context,
                      AppRouter.meetingRoom,
                      arguments: {'id': data['public_id'], 'title': data['title'], 'isHost': true},
                    );
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
                      onTap: () => Navigator.pushNamed(
                        ctx,
                        AppRouter.meetingDetails,
                        arguments: {'id': filtered[i]['public_id']},
                      ),
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
    final projectName = meeting['project_name']?.toString() ?? '—';
    final startTime =
        _formatDate(meeting['scheduled_start_time']?.toString());
    final participantCount = meeting['participant_count'] ?? 0;

    return Card(
      margin: const EdgeInsets.only(bottom: 12),
      clipBehavior: Clip.antiAlias,
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
                      style: const TextStyle(
                          fontSize: 16, fontWeight: FontWeight.w600),
                    ),
                  ),
                  const SizedBox(width: 8),
                  statusBadge,
                ],
              ),
              const SizedBox(height: 8),
              Row(
                children: [
                  const Icon(Icons.folder_outlined,
                      size: 14, color: Colors.grey),
                  const SizedBox(width: 4),
                  Expanded(
                    child: Text(
                      projectName,
                      style: const TextStyle(fontSize: 13, color: Colors.grey),
                      overflow: TextOverflow.ellipsis,
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 4),
              Row(
                children: [
                  const Icon(Icons.schedule, size: 14, color: Colors.grey),
                  const SizedBox(width: 4),
                  Text(
                    startTime,
                    style: const TextStyle(fontSize: 13, color: Colors.grey),
                  ),
                ],
              ),
              const SizedBox(height: 4),
              Row(
                children: [
                  const Icon(Icons.people_outline,
                      size: 14, color: Colors.grey),
                  const SizedBox(width: 4),
                  Text(
                    '$participantCount participant${participantCount == 1 ? '' : 's'}',
                    style: const TextStyle(fontSize: 13, color: Colors.grey),
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
