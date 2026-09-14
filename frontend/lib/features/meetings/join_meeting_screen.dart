import 'dart:convert';

import 'package:flutter/material.dart';
import '../../core/navigation/app_router.dart';
import '../../core/services/api_service.dart';
import '../../core/widgets/enterprise_scaffold.dart';

class JoinMeetingScreen extends StatefulWidget {
  final String? initialCode;

  const JoinMeetingScreen({super.key, this.initialCode});

  @override
  State<JoinMeetingScreen> createState() => _JoinMeetingScreenState();
}

class _JoinMeetingScreenState extends State<JoinMeetingScreen> {
  final _api = ApiService();
  final _codeCtrl = TextEditingController();
  bool _loading = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    if (widget.initialCode != null) {
      _codeCtrl.text = widget.initialCode!;
      _join();
    }
  }

  @override
  void dispose() {
    _codeCtrl.dispose();
    super.dispose();
  }

  Future<void> _join() async {
    var code = _codeCtrl.text.trim();
    final marker = code.indexOf('/#/join/');
    if (marker >= 0) code = code.substring(marker + '/#/join/'.length).split('?').first;
    code = Uri.decodeComponent(code).trim().toUpperCase();
    if (code.isEmpty) {
      setState(() => _error = 'Please enter a meeting code');
      return;
    }

    setState(() {
      _loading = true;
      _error = null;
    });

    try {
      final res = await _api.post('/meetings/join', body: {'invite_code': code});

      if (res.statusCode == 200) {
        final data = json.decode(res.body);
        if (mounted) {
          Navigator.pushReplacementNamed(
            context,
            AppRouter.meetingRoom,
            arguments: {
              'id': data['meeting_id'],
              'title': data['meeting_title'] ?? data['meeting_id'],
              'livekitUrl': data['livekit_url'],
              'token': data['token'],
              'roomName': data['room_name'],
              'isHost': data['participant']?['role'] == 'HOST',
            },
          );
        }
      } else {
        final errJson = json.decode(res.body);
        setState(() {
          _error = errJson['detail'] ?? 'Failed to join meeting';
          _loading = false;
        });
      }
    } catch (e) {
      if (e is ApiException && e.statusCode == 401) {
        await _api.clearToken();
        if (mounted) {
          setState(() {
            _loading = false;
            _error = 'Your session expired. Please sign in again, then use this meeting code.';
          });
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(content: Text('Please sign in again to join this meeting.')),
          );
        }
        return;
      }
      setState(() {
        _error = e.toString();
        _loading = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return EnterpriseScaffold(
      title: 'Join Meeting',
      currentRoute: AppRouter.dashboard,
      child: Center(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(24),
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 400),
            child: Card(
              child: Padding(
                padding: const EdgeInsets.all(24),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    const Icon(Icons.videocam_rounded, size: 48, color: Color(0xFFFF5722)),
                    const SizedBox(height: 16),
                    Text(
                      'Join a Meeting',
                      style: Theme.of(context).textTheme.headlineSmall?.copyWith(
                        fontWeight: FontWeight.bold,
                      ),
                    ),
                    const SizedBox(height: 8),
                    Text(
                      'Enter the invite code shared with you',
                      style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                        color: const Color(0xFF64748B),
                      ),
                      textAlign: TextAlign.center,
                    ),
                    const SizedBox(height: 24),
                    TextField(
                      controller: _codeCtrl,
                      onSubmitted: (_) => _join(),
                      textCapitalization: TextCapitalization.characters,
                      decoration: const InputDecoration(
                        labelText: 'Invite Code',
                        hintText: 'MTG-ABC123',
                        prefixIcon: Icon(Icons.videocam_rounded),
                        border: OutlineInputBorder(),
                      ),
                    ),
                    const SizedBox(height: 16),
                    if (_error != null)
                      Container(
                        padding: const EdgeInsets.all(12),
                        decoration: BoxDecoration(
                          color: const Color(0xFFFEF2F2),
                          borderRadius: BorderRadius.circular(8),
                          border: Border.all(color: const Color(0xFFEF4444)),
                        ),
                        child: Row(
                          children: [
                            const Icon(Icons.error_outline, color: Color(0xFFEF4444), size: 20),
                            const SizedBox(width: 8),
                            Expanded(
                              child: Text(
                                _error!,
                                style: const TextStyle(color: Color(0xFFEF4444), fontSize: 13),
                              ),
                            ),
                          ],
                        ),
                      ),
                    const SizedBox(height: 20),
                    SizedBox(
                      width: double.infinity,
                      child: FilledButton.icon(
                        onPressed: _loading ? null : _join,
                        icon: _loading
                            ? const SizedBox(
                                width: 18,
                                height: 18,
                                child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
                              )
                            : const Icon(Icons.login_rounded),
                        label: Text(_loading ? 'Joining...' : 'Join Meeting'),
                        style: FilledButton.styleFrom(
                          backgroundColor: const Color(0xFFFF5722),
                          padding: const EdgeInsets.symmetric(vertical: 14),
                        ),
                      ),
                    ),
                    const SizedBox(height: 12),
                    TextButton(
                      onPressed: () => Navigator.pushNamed(context, AppRouter.dashboard),
                      child: const Text('Back to Dashboard'),
                    ),
                  ],
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}
