import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../../core/navigation/app_router.dart';
import '../../core/providers/auth_provider.dart';
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
      // Delay by one frame so the widget is fully built before attempting join
      WidgetsBinding.instance.addPostFrameCallback((_) => _join());
    }
  }

  @override
  void dispose() {
    _codeCtrl.dispose();
    super.dispose();
  }

  /// Map backend error status codes to user-friendly, specific messages.
  String _errorMessageFor(ApiException e) {
    switch (e.statusCode) {
      case 401:
        return 'Your session has expired. Please sign in again.';
      case 403:
        return 'You are not authorized to join this meeting.';
      case 404:
        return 'Meeting code not found. Check the invite code and try again.';
      case 400:
        return 'This meeting has already ended or is no longer active.';
      case 503:
        return 'Meeting server is temporarily unavailable. Please try again in a moment.';
      default:
        // Show the backend's actual message if it's specific enough
        final msg = e.message;
        if (msg.isNotEmpty &&
            msg != 'Could not validate credentials' &&
            !msg.startsWith('An error occurred')) {
          return msg;
        }
        return 'Could not join meeting. Please try again.';
    }
  }

  Future<void> _join() async {
    var code = _codeCtrl.text.trim();
    // Strip full URL if the user pasted a join link
    final marker = code.indexOf('/#/join/');
    if (marker >= 0) {
      code = code.substring(marker + '/#/join/'.length).split('?').first;
    }
    code = Uri.decodeComponent(code).trim().toUpperCase();

    if (code.isEmpty) {
      setState(() => _error = 'Please enter a meeting code');
      return;
    }

    setState(() {
      _loading = true;
      _error = null;
    });

    // Safety check: verify we actually have a valid auth token before calling
    // the backend (avoids an unnecessary network round-trip that will 401).
    if (!_api.isAuthenticated) {
      final authProvider = Provider.of<AuthProvider>(context, listen: false);
      authProvider.handleGlobalAuthFailure();
      return;
    }

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
        // Unexpected 2xx-3xx non-200 responses (rare with FastAPI)
        String msg = 'Failed to join meeting';
        try {
          final errJson = json.decode(res.body);
          msg = errJson['detail']?.toString() ?? msg;
        } catch (_) {}
        setState(() {
          _error = msg;
          _loading = false;
        });
      }
    } on ApiException catch (e) {
      if (e.statusCode == 401) {
        // ApiService already attempted token refresh and it failed.
        // The onAuthFailure callback has already been fired, which calls
        // AuthProvider.handleGlobalAuthFailure() → router redirects to login.
        // We just stop loading; the widget will be replaced by the login page.
        if (mounted) {
          setState(() => _loading = false);
        }
        return;
      }
      setState(() {
        _error = _errorMessageFor(e);
        _loading = false;
      });
    } catch (e) {
      setState(() {
        _error = 'Unexpected error: $e';
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
                    const Icon(Icons.videocam_rounded,
                        size: 48, color: Color(0xFFFF5722)),
                    const SizedBox(height: 16),
                    Text(
                      'Join a Meeting',
                      style:
                          Theme.of(context).textTheme.headlineSmall?.copyWith(
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
                            const Icon(Icons.error_outline,
                                color: Color(0xFFEF4444), size: 20),
                            const SizedBox(width: 8),
                            Expanded(
                              child: Text(
                                _error!,
                                style: const TextStyle(
                                    color: Color(0xFFEF4444), fontSize: 13),
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
                                child: CircularProgressIndicator(
                                    strokeWidth: 2, color: Colors.white),
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
                      onPressed: () =>
                          Navigator.pushNamed(context, AppRouter.dashboard),
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
