import 'dart:convert';
// ignore: avoid_web_libraries_in_flutter
import 'dart:html' as html;
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:http/http.dart' as http;
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
  bool _uploading = false;
  String? _uploadStatus;

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

  Future<void> _uploadRecording() async {
    final html.FileUploadInputElement uploadInput = html.FileUploadInputElement();
    uploadInput.accept = 'audio/*,video/*,.wav,.mp3,.m4a,.flac,.ogg,.webm,.mp4';
    uploadInput.click();

    uploadInput.onChange.listen((e) async {
      final files = uploadInput.files;
      if (files == null || files.isEmpty) return;
      final file = files[0];

      setState(() {
        _uploading = true;
        _uploadStatus = 'Reading file...';
      });

      final reader = html.FileReader();
      reader.readAsArrayBuffer(file);
      reader.onLoadEnd.listen((e) async {
        try {
          setState(() => _uploadStatus = 'Uploading ${file.name}...');

          final bytes = reader.result as Uint8List;
          final token = _api.token;

          final uri = Uri.parse('${ApiService.baseUrl}/meetings/${widget.meetingId}/recordings');
          final request = http.MultipartRequest('POST', uri);
          if (token != null) {
            request.headers['Authorization'] = 'Bearer $token';
          }
          request.files.add(http.MultipartFile.fromBytes(
            'file',
            bytes,
            filename: file.name,
          ));

          final streamedResponse = await request.send();
          final responseBody = await streamedResponse.stream.bytesToString();

          if (streamedResponse.statusCode == 201 || streamedResponse.statusCode == 200) {
            setState(() {
              _uploading = false;
              _uploadStatus = null;
            });
            if (mounted) {
              ScaffoldMessenger.of(context).showSnackBar(
                const SnackBar(
                  content: Text('Recording uploaded! AI processing will begin automatically.'),
                  backgroundColor: Colors.green,
                ),
              );
            }
            // Reload to show updated status
            _load();
          } else {
            String errorDetail = 'Upload failed (${streamedResponse.statusCode})';
            try {
              final errJson = json.decode(responseBody);
              errorDetail = errJson['detail'] ?? errorDetail;
            } catch (_) {}
            setState(() {
              _uploading = false;
              _uploadStatus = null;
            });
            if (mounted) {
              ScaffoldMessenger.of(context).showSnackBar(
                SnackBar(content: Text(errorDetail), backgroundColor: Colors.red),
              );
            }
          }
        } catch (err) {
          setState(() {
            _uploading = false;
            _uploadStatus = null;
          });
          if (mounted) {
            ScaffoldMessenger.of(context).showSnackBar(
              SnackBar(content: Text('Upload error: $err'), backgroundColor: Colors.red),
            );
          }
        }
      });
    });
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
            onPressed: _meeting == null ? null : () async {
              try {
                await _api.post('/meetings/${widget.meetingId}/start');
              } catch (_) {}
              if (mounted) {
                Navigator.pushNamed(
                  context, 
                  AppRouter.meetingRoom, 
                  arguments: {
                    'id': widget.meetingId, 
                    'title': _meeting!['title'], 
                    'isHost': true, 
                    'inviteCode': _meeting!['invite_code']
                  }
                );
              }
            },
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
    final transcriptionStatus = meeting['transcription_status'] as String? ?? 'pending';
    final analysisStatus = meeting['analysis_status'] as String? ?? 'pending';

    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        // Meeting Info Card
        Card(
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('${meeting['title'] ?? 'Untitled meeting'}', style: Theme.of(context).textTheme.headlineSmall),
                const SizedBox(height: 8),
                Row(
                  children: [
                    _StatusChip(meeting['status'] ?? 'UNKNOWN'),
                    const SizedBox(width: 8),
                    Text(meeting['public_id'] ?? widget.meetingId, style: TextStyle(color: Colors.grey[600], fontSize: 12)),
                  ],
                ),
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
                Wrap(
                  spacing: 12,
                  runSpacing: 12,
                  children: [
                    FilledButton.icon(
                      onPressed: () async {
                        try {
                          await _api.post('/meetings/${widget.meetingId}/start');
                        } catch (_) {}
                        if (mounted) {
                          Navigator.pushNamed(
                            context, 
                            AppRouter.meetingRoom, 
                            arguments: {
                              'id': widget.meetingId, 
                              'title': meeting['title'], 
                              'isHost': true, 
                              'inviteCode': meeting['invite_code']
                            }
                          );
                        }
                      },
                      icon: const Icon(Icons.play_arrow),
                      label: const Text('Start / Join Meeting'),
                    ),
                    OutlinedButton.icon(
                      onPressed: _uploading ? null : _uploadRecording,
                      icon: _uploading
                          ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2))
                          : const Icon(Icons.upload_file),
                      label: Text(_uploading ? (_uploadStatus ?? 'Uploading...') : 'Upload Recording'),
                    ),
                  ],
                ),
              ],
            ),
          ),
        ),

        const SizedBox(height: 12),

        // AI Processing Status Card
        Card(
          color: _getStatusColor(transcriptionStatus, analysisStatus),
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Row(
              children: [
                Icon(
                  _getStatusIcon(transcriptionStatus, analysisStatus),
                  color: _getStatusIconColor(transcriptionStatus, analysisStatus),
                  size: 28,
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        'AI Intelligence',
                        style: TextStyle(fontWeight: FontWeight.bold, fontSize: 16, color: _getStatusTextColor(transcriptionStatus, analysisStatus)),
                      ),
                      const SizedBox(height: 4),
                      Text(
                        _getStatusMessage(transcriptionStatus, analysisStatus),
                        style: TextStyle(fontSize: 13, color: _getStatusTextColor(transcriptionStatus, analysisStatus).withOpacity(0.8)),
                      ),
                    ],
                  ),
                ),
                if (transcriptionStatus == 'processing' || analysisStatus == 'processing')
                  const SizedBox(width: 24, height: 24, child: CircularProgressIndicator(strokeWidth: 2)),
              ],
            ),
          ),
        ),

        const SizedBox(height: 12),

        // Intelligence Navigation Grid
        Card(
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('Meeting Vault', style: Theme.of(context).textTheme.titleMedium?.copyWith(fontWeight: FontWeight.bold)),
                const SizedBox(height: 4),
                Text('View who said what, AI summaries, topics, decisions, and tasks.', style: TextStyle(color: Colors.grey[600], fontSize: 13)),
                const SizedBox(height: 16),
                GridView.count(
                  crossAxisCount: MediaQuery.of(context).size.width > 600 ? 3 : 2,
                  shrinkWrap: true,
                  physics: const NeverScrollableScrollPhysics(),
                  mainAxisSpacing: 8,
                  crossAxisSpacing: 8,
                  childAspectRatio: 2.5,
                  children: [
                    _VaultTile(icon: Icons.groups, label: 'Participants', color: Colors.blue, onTap: () => Navigator.pushNamed(context, AppRouter.participants, arguments: {'id': widget.meetingId})),
                    _VaultTile(icon: Icons.record_voice_over, label: 'Transcript', color: Colors.teal, subtitle: 'Who said what', onTap: () => Navigator.pushNamed(context, AppRouter.transcript, arguments: {'id': widget.meetingId})),
                    _VaultTile(icon: Icons.summarize, label: 'AI Summary', color: Colors.purple, onTap: () => Navigator.pushNamed(context, AppRouter.summary, arguments: {'id': widget.meetingId})),
                    _VaultTile(icon: Icons.topic, label: 'Topics', color: Colors.orange, onTap: () => Navigator.pushNamed(context, AppRouter.topics, arguments: {'id': widget.meetingId})),
                    _VaultTile(icon: Icons.gavel, label: 'Decisions', color: Colors.indigo, onTap: () => Navigator.pushNamed(context, AppRouter.decisions, arguments: {'id': widget.meetingId})),
                    _VaultTile(icon: Icons.assignment_turned_in, label: 'Action Items', color: Colors.green, onTap: () => Navigator.pushNamed(context, AppRouter.tasks, arguments: {'id': widget.meetingId})),
                  ],
                ),
              ],
            ),
          ),
        ),
      ],
    );
  }

  Color _getStatusColor(String t, String a) {
    if (t == 'completed' && a == 'completed') return const Color(0xFFE8F5E9);
    if (t == 'failed' || a == 'failed') return const Color(0xFFFCE4EC);
    if (t == 'processing' || a == 'processing' || t == 'queued' || a == 'queued') return const Color(0xFFFFF3E0);
    return const Color(0xFFF5F5F5);
  }

  IconData _getStatusIcon(String t, String a) {
    if (t == 'completed' && a == 'completed') return Icons.check_circle;
    if (t == 'failed' || a == 'failed') return Icons.error;
    if (t == 'processing' || a == 'processing') return Icons.psychology;
    if (t == 'queued' || a == 'queued') return Icons.hourglass_top;
    return Icons.cloud_upload;
  }

  Color _getStatusIconColor(String t, String a) {
    if (t == 'completed' && a == 'completed') return Colors.green;
    if (t == 'failed' || a == 'failed') return Colors.red;
    if (t == 'processing' || a == 'processing') return Colors.orange;
    return Colors.grey;
  }

  Color _getStatusTextColor(String t, String a) {
    if (t == 'completed' && a == 'completed') return const Color(0xFF2E7D32);
    if (t == 'failed' || a == 'failed') return const Color(0xFFC62828);
    if (t == 'processing' || a == 'processing' || t == 'queued' || a == 'queued') return const Color(0xFFE65100);
    return const Color(0xFF616161);
  }

  String _getStatusMessage(String t, String a) {
    if (t == 'completed' && a == 'completed') return 'Analysis complete! Tap any section below to explore.';
    if (t == 'failed') return 'Transcription failed. Try re-uploading the recording.';
    if (a == 'failed') return 'Analysis failed. The transcript may still be available.';
    if (t == 'processing') return 'Transcribing audio and identifying speakers...';
    if (a == 'processing') return 'AI is analyzing the transcript for insights...';
    if (t == 'queued' || a == 'queued') return 'Recording queued for AI processing...';
    return 'Upload a recording to unlock AI insights for this meeting.';
  }
}

class _StatusChip extends StatelessWidget {
  final String status;
  const _StatusChip(this.status);

  @override
  Widget build(BuildContext context) {
    Color color;
    switch (status.toUpperCase()) {
      case 'LIVE':
        color = Colors.red;
        break;
      case 'COMPLETED':
        color = Colors.green;
        break;
      case 'SCHEDULED':
        color = Colors.blue;
        break;
      default:
        color = Colors.grey;
    }
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
      decoration: BoxDecoration(
        color: color.withOpacity(0.1),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: color.withOpacity(0.4)),
      ),
      child: Text(status, style: TextStyle(color: color, fontSize: 12, fontWeight: FontWeight.w600)),
    );
  }
}

class _VaultTile extends StatelessWidget {
  final IconData icon;
  final String label;
  final String? subtitle;
  final Color color;
  final VoidCallback onTap;

  const _VaultTile({required this.icon, required this.label, required this.color, required this.onTap, this.subtitle});

  @override
  Widget build(BuildContext context) {
    return Material(
      color: color.withOpacity(0.08),
      borderRadius: BorderRadius.circular(12),
      child: InkWell(
        borderRadius: BorderRadius.circular(12),
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
          child: Row(
            children: [
              Icon(icon, color: color, size: 24),
              const SizedBox(width: 10),
              Expanded(
                child: Column(
                  mainAxisAlignment: MainAxisAlignment.center,
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(label, style: TextStyle(fontWeight: FontWeight.w600, fontSize: 13, color: color.withOpacity(0.9))),
                    if (subtitle != null)
                      Text(subtitle!, style: TextStyle(fontSize: 10, color: Colors.grey[600])),
                  ],
                ),
              ),
              Icon(Icons.chevron_right, color: color.withOpacity(0.5), size: 18),
            ],
          ),
        ),
      ),
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
