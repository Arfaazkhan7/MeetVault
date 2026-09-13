import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import '../../core/navigation/app_router.dart';
import '../../core/services/api_service.dart';
import '../../core/widgets/enterprise_scaffold.dart';

class MeetingDetailsScreen extends StatefulWidget {
  final String meetingId;

  const MeetingDetailsScreen({super.key, required this.meetingId});

  @override
  State<MeetingDetailsScreen> createState() => _MeetingDetailsScreenState();
}

class _MeetingDetailsScreenState extends State<MeetingDetailsScreen> {
  final _api = ApiService();
  Map<String, dynamic>? _meeting;
  bool _loading = true;
  String? _error;

  bool get _isCreateMode {
    final args = ModalRoute.of(context)?.settings.arguments as Map<String, dynamic>?;
    return args != null && args['create'] == true;
  }

  String? get _projectId {
    final args = ModalRoute.of(context)?.settings.arguments as Map<String, dynamic>?;
    return args != null ? args['id'] as String? : null;
  }

  @override
  void initState() {
    super.initState();
    if (_isCreateMode) {
      setState(() => _loading = false);
    } else {
      _load();
    }
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final response = await _api.get('/meetings/${widget.meetingId}');
      setState(() {
        _meeting = json.decode(response.body);
        _loading = false;
      });
    } catch (error) {
      setState(() {
        _error = error.toString();
        _loading = false;
      });
    }
  }

  Future<void> _createMeeting(String title, String? description) async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final projectId = _projectId;
      if (projectId == null) {
        throw Exception('Missing project for meeting creation');
      }

      final projectResp = await _api.get('/projects/$projectId');
      String companyId;
      if (projectResp.statusCode == 200) {
        final project = json.decode(projectResp.body) as Map<String, dynamic>;
        companyId = project['company_id']?.toString() ?? '';
        if (companyId.isEmpty) {
          throw Exception('Project is missing company information');
        }
      } else {
        throw Exception('Unable to load project details');
      }

      final res = await _api.post('/companies/$companyId/meetings', body: {
        'title': title.trim(),
        'description': description?.trim(),
        'project_id': projectId,
      });

      if (res.statusCode == 201) {
        final data = json.decode(res.body);
        if (mounted) {
          // Replace current route with the meeting details route for the new meeting.
          // This will re-mount the screen in non-create mode.
          Navigator.pushReplacementNamed(
            context,
            AppRouter.meetingDetails,
            arguments: {'id': data['public_id']},
          );
        }
      } else {
        final errJson = json.decode(res.body);
        setState(() {
          _error = errJson['detail'] ?? 'Failed to create meeting';
          _loading = false;
        });
      }
    } catch (e) {
      setState(() {
        _error = e.toString();
        _loading = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return EnterpriseScaffold(
      title: _isCreateMode ? 'New Meeting' : 'Meeting Details',
      currentRoute: AppRouter.meetings,
      actions: [
        if (!_isCreateMode) ...[
          IconButton(tooltip: 'Refresh', onPressed: _load, icon: const Icon(Icons.refresh)),
          IconButton(
            tooltip: 'Join room',
            onPressed: _meeting == null ? null : () => Navigator.pushNamed(context, AppRouter.meetingRoom, arguments: {'id': widget.meetingId, 'title': _meeting!['title'], 'isHost': true}),
            icon: const Icon(Icons.video_call),
          ),
        ],
      ],
      child: _body(),
    );
  }

  Widget _body() {
    if (_loading) {
      return const Center(child: CircularProgressIndicator());
    }
    if (_error != null) {
      return UiState.error(_error!, onRetry: _isCreateMode ? null : _load);
    }

    if (_isCreateMode) {
      return _CreateMeetingForm(onSubmit: _createMeeting);
    }

    final meeting = _meeting ?? {};
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        Card(
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('${meeting['title'] ?? 'Untitled meeting'}', style: Theme.of(context).textTheme.headlineSmall),
                const SizedBox(height: 8),
                Text('${meeting['public_id'] ?? widget.meetingId}  ${meeting['status'] ?? ''}'),
                if (meeting['invite_code'] != null) ...[
                  const SizedBox(height: 12),
                  Row(
                    children: [
                      const Icon(Icons.vpn_key_rounded, size: 16, color: Color(0xFF64748B)),
                      const SizedBox(width: 8),
                      Text('Invite Code: ', style: const TextStyle(fontWeight: FontWeight.w500, color: Color(0xFF334155))),
                      Expanded(child: Text(meeting['invite_code'], style: const TextStyle(fontFamily: 'monospace', fontWeight: FontWeight.bold, color: Color(0xFFFF5722)))),
                      const Spacer(),
                      IconButton(
                        icon: const Icon(Icons.copy_rounded, size: 18),
                        onPressed: () async {
                          await Clipboard.setData(ClipboardData(text: meeting['invite_code'].toString()));
                          ScaffoldMessenger.of(context).showSnackBar(
                            const SnackBar(content: Text('Invite code copied')),
                          );
                        },
                        tooltip: 'Copy invite code',
                      ),
                      IconButton(
                        icon: const Icon(Icons.link_rounded, size: 18),
                        onPressed: () async {
                          final link = '${Uri.base.origin}/#/join/${Uri.encodeComponent(meeting['invite_code'].toString())}';
                          await Clipboard.setData(ClipboardData(text: link));
                          if (mounted) ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Invite link copied')));
                        },
                        tooltip: 'Copy invite link',
                      ),
                    ],
                  ),
                ],
                if (meeting['description'] != null) ...[
                  const SizedBox(height: 12),
                  Text('${meeting['description']}'),
                ],
                const SizedBox(height: 16),
                FilledButton.icon(
                  onPressed: () => Navigator.pushNamed(context, AppRouter.meetingRoom, arguments: {'id': widget.meetingId, 'title': meeting['title'], 'isHost': true}),
                  icon: const Icon(Icons.play_arrow),
                  label: const Text('Start / Join Meeting'),
                ),
              ],
            ),
          ),
        ),
        const SizedBox(height: 12),
        Wrap(
          spacing: 8,
          runSpacing: 8,
          children: [
            _Action('Participants', Icons.groups, AppRouter.participants),
            _Action('Transcript', Icons.subject, AppRouter.transcript),
            _Action('Summary', Icons.summarize, AppRouter.summary),
            _Action('Topics', Icons.topic, AppRouter.topics),
            _Action('Decisions', Icons.fact_check, AppRouter.decisions),
            _Action('Tasks', Icons.assignment, AppRouter.tasks),
          ].map((action) => FilledButton.icon(
                onPressed: () => Navigator.pushNamed(context, action.route, arguments: {'id': widget.meetingId}),
                icon: Icon(action.icon),
                label: Text(action.label),
              )).toList(),
        ),
      ],
    );
  }
}

class _CreateMeetingForm extends StatefulWidget {
  final Future<void> Function(String title, String? description) onSubmit;

  const _CreateMeetingForm({required this.onSubmit});

  @override
  State<_CreateMeetingForm> createState() => _CreateMeetingFormState();
}

class _CreateMeetingFormState extends State<_CreateMeetingForm> {
  final _titleCtrl = TextEditingController();
  final _descCtrl = TextEditingController();
  bool _submitting = false;

  @override
  void dispose() {
    _titleCtrl.dispose();
    _descCtrl.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    final title = _titleCtrl.text.trim();
    if (title.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Meeting title is required')),
      );
      return;
    }
    setState(() => _submitting = true);
    await widget.onSubmit(title, _descCtrl.text.isEmpty ? null : _descCtrl.text);
  }

  @override
  Widget build(BuildContext context) {
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        Card(
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('Schedule Meeting', style: Theme.of(context).textTheme.headlineSmall),
                const SizedBox(height: 16),
                TextField(
                  controller: _titleCtrl,
                  decoration: const InputDecoration(
                    labelText: 'Meeting Title',
                    hintText: 'e.g. Architecture Sync',
                    border: OutlineInputBorder(),
                  ),
                  textInputAction: TextInputAction.next,
                ),
                const SizedBox(height: 16),
                TextField(
                  controller: _descCtrl,
                  decoration: const InputDecoration(
                    labelText: 'Description',
                    hintText: 'Agenda or details',
                    border: OutlineInputBorder(),
                  ),
                  maxLines: 3,
                ),
                const SizedBox(height: 20),
                FilledButton.icon(
                  onPressed: _submitting ? null : _submit,
                  icon: _submitting
                      ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
                      : const Icon(Icons.video_call),
                  label: Text(_submitting ? 'Creating...' : 'Create Meeting'),
                ),
              ],
            ),
          ),
        ),
      ],
    );
  }
}

class _Action {
  final String label;
  final IconData icon;
  final String route;
  const _Action(this.label, this.icon, this.route);
}
