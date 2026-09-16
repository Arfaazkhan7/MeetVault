import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:http/http.dart' as http;
import 'package:livekit_client/livekit_client.dart';

class MeetingRoomScreen extends StatefulWidget {
  final String meetingId;
  final String meetingTitle;
  final String authToken;
  final String apiBaseUrl;
  final bool isHost;
  final String? livekitUrl;
  final String? token;
  final String? roomName;
  final String? inviteCode;

  const MeetingRoomScreen({
    super.key,
    required this.meetingId,
    required this.meetingTitle,
    required this.authToken,
    this.apiBaseUrl = 'http://localhost:8000/api/v1',
    this.isHost = false,
    this.livekitUrl,
    this.token,
    this.roomName,
    this.inviteCode,
  });

  @override
  State<MeetingRoomScreen> createState() => _MeetingRoomScreenState();
}

class _DeviceErrorInfo {
  final String state;
  final String userMessage;

  const _DeviceErrorInfo({required this.state, required this.userMessage});
}

class _MeetingRoomScreenState extends State<MeetingRoomScreen> {
  Room? _room;
  EventsListener<RoomEvent>? _listener;
  Timer? _timer;
  Duration _elapsed = Duration.zero;
  DateTime? _joinedAt;
  bool _isConnecting = true;
  bool _isLeaving = false;

  // Real media track booleans synchronized with published tracks
  bool _microphoneEnabled = false;
  bool _cameraEnabled = false;
  bool _screenShareEnabled = false;

  // Granular device & connection status tracking
  String _connectionStatus = 'Connecting';
  String _cameraState = 'Off'; // 'Off', 'Enabling', 'On', 'Permission Denied', 'No Device', 'In Use', 'Failed'
  String _microphoneState = 'Off'; // 'Off', 'Enabling', 'On', 'Permission Denied', 'No Device', 'In Use', 'Failed'

  String? _cameraErrorMessage;
  String? _microphoneErrorMessage;
  String? _errorMessage;
  String? _inviteCode;
  Participant? _pinnedParticipant;

  @override
  void initState() {
    super.initState();
    _inviteCode = widget.inviteCode;
    _connect();
  }

  @override
  void dispose() {
    _timer?.cancel();
    _listener?.dispose();
    _room?.disconnect();
    super.dispose();
  }

  Future<void> _connect() async {
    setState(() {
      _isConnecting = true;
      _errorMessage = null;
      _connectionStatus = 'Requesting access';
      _microphoneEnabled = false;
      _cameraEnabled = false;
      _microphoneState = 'Off';
      _cameraState = 'Off';
      _cameraErrorMessage = null;
      _microphoneErrorMessage = null;
    });

    try {
      String livekitUrl;
      String token;
      String roomName;

      if (widget.livekitUrl != null && widget.token != null && widget.roomName != null) {
        livekitUrl = widget.livekitUrl!;
        token = widget.token!;
        roomName = widget.roomName!;
      } else {
        final connection = await _requestConnection();
        livekitUrl = connection.livekitUrl;
        token = connection.token;
        roomName = connection.roomName;
      }

      setState(() => _connectionStatus = 'Joining room');
      await _recordJoin();

      final room = Room();
      final listener = room.createListener();
      listener
        ..on<RoomDisconnectedEvent>((event) {
          if (mounted) {
            setState(() => _connectionStatus = 'Disconnected');
          }
        })
        ..on<ParticipantConnectedEvent>((event) => _refresh())
        ..on<ParticipantDisconnectedEvent>((event) => _refresh())
        ..on<TrackSubscribedEvent>((event) => _refresh())
        ..on<TrackUnsubscribedEvent>((event) => _refresh())
        ..on<LocalTrackPublishedEvent>((event) {
          _syncLocalMediaStates();
          _refresh();
        })
        ..on<LocalTrackUnpublishedEvent>((event) {
          _syncLocalMediaStates();
          _refresh();
        })
        ..on<TrackMutedEvent>((event) {
          _syncLocalMediaStates();
          _refresh();
        })
        ..on<TrackUnmutedEvent>((event) {
          _syncLocalMediaStates();
          _refresh();
        });

      setState(() => _connectionStatus = 'Connecting to server');

      await room.connect(
        livekitUrl,
        token,
        roomOptions: const RoomOptions(
          adaptiveStream: true,
          dynacast: true,
        ),
      );

      _joinedAt = DateTime.now();
      _timer = Timer.periodic(const Duration(seconds: 1), (_) {
        if (_joinedAt == null || !mounted) return;
        setState(() => _elapsed = DateTime.now().difference(_joinedAt!));
      });

      setState(() {
        _room = room;
        _listener = listener;
        _isConnecting = false;
        _connectionStatus = 'Connected';
      });

      // Initialize microphone and camera independently
      await _initMicrophone();
      await _initCamera();
    } catch (error) {
      String msg = error.toString();
      if (msg.contains('LIVEKIT_URL is not configured') || msg.contains('LIVEKIT_API_KEY is not configured')) {
        msg = 'LiveKit is not configured on the server. Please contact your administrator.';
      } else if (msg.contains('SocketException') || msg.contains('Failed to fetch')) {
        msg = 'Cannot reach the meeting server. Please check your connection.';
      }
      setState(() {
        _isConnecting = false;
        _connectionStatus = 'Failed';
        _errorMessage = msg;
      });
    }
  }

  Future<_MeetingConnection> _requestConnection() async {
    final response = await http.post(
      Uri.parse('${widget.apiBaseUrl}/meetings/${widget.meetingId}/room/connect'),
      headers: _headers,
    );
    if (response.statusCode != 200) {
      final body = json.decode(response.body);
      throw Exception(body['detail'] ?? 'Unable to enter meeting (${response.statusCode})');
    }
    return _MeetingConnection.fromJson(json.decode(response.body));
  }

  Future<void> _recordJoin() async {
    try {
      await http.post(
        Uri.parse('${widget.apiBaseUrl}/meetings/${widget.meetingId}/room/join'),
        headers: _headers,
      );
    } catch (_) {}
  }

  Future<void> _recordLeave() async {
    try {
      await http.post(
        Uri.parse('${widget.apiBaseUrl}/meetings/${widget.meetingId}/room/leave'),
        headers: _headers,
      );
    } catch (_) {}
  }

  Map<String, String> get _headers => {
    'Authorization': 'Bearer ${widget.authToken}',
    'Content-Type': 'application/json',
  };

  Future<void> _initMicrophone() async {
    final room = _room;
    if (room == null || room.localParticipant == null) return;

    setState(() {
      _microphoneState = 'Enabling';
      _microphoneErrorMessage = null;
    });

    try {
      await room.localParticipant!.setMicrophoneEnabled(true);
      _syncLocalMediaStates();

      if (!_microphoneEnabled) {
        setState(() {
          _microphoneState = 'Failed';
          _microphoneErrorMessage = 'Microphone could not be published.';
        });
      } else {
        setState(() {
          _microphoneState = 'On';
          _microphoneErrorMessage = null;
        });
      }
    } catch (e) {
      debugPrint('[MeetingRoomScreen] Microphone error: $e');
      final err = _classifyDeviceError(e, 'Microphone');
      setState(() {
        _microphoneEnabled = false;
        _microphoneState = err.state;
        _microphoneErrorMessage = err.userMessage;
      });
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(err.userMessage),
            backgroundColor: const Color(0xFFDC2626),
            duration: const Duration(seconds: 4),
            action: SnackBarAction(
              label: 'Retry',
              textColor: Colors.white,
              onPressed: _initMicrophone,
            ),
          ),
        );
      }
    }
  }

  Future<void> _initCamera() async {
    final room = _room;
    if (room == null || room.localParticipant == null) return;

    setState(() {
      _cameraState = 'Enabling';
      _cameraErrorMessage = null;
    });

    try {
      await room.localParticipant!.setCameraEnabled(true);
      _syncLocalMediaStates();

      if (!_cameraEnabled) {
        setState(() {
          _cameraState = 'Failed';
          _cameraErrorMessage = 'Camera could not be published.';
        });
      } else {
        setState(() {
          _cameraState = 'On';
          _cameraErrorMessage = null;
        });
      }
    } catch (e) {
      debugPrint('[MeetingRoomScreen] Camera error: $e');
      final err = _classifyDeviceError(e, 'Camera');
      setState(() {
        _cameraEnabled = false;
        _cameraState = err.state;
        _cameraErrorMessage = err.userMessage;
      });
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(err.userMessage),
            backgroundColor: const Color(0xFFDC2626),
            duration: const Duration(seconds: 4),
            action: SnackBarAction(
              label: 'Retry',
              textColor: Colors.white,
              onPressed: _initCamera,
            ),
          ),
        );
      }
    }
  }

  void _syncLocalMediaStates() {
    final participant = _room?.localParticipant;
    if (participant == null) {
      _microphoneEnabled = false;
      _cameraEnabled = false;
      return;
    }

    bool hasAudio = false;
    for (final pub in participant.audioTrackPublications) {
      if (pub.kind == TrackType.AUDIO && !pub.muted && pub.track != null) {
        hasAudio = true;
        break;
      }
    }

    bool hasVideo = false;
    for (final pub in participant.videoTrackPublications) {
      if (pub.kind == TrackType.VIDEO && !pub.muted && pub.track != null && pub.source != TrackSource.screenShareVideo) {
        hasVideo = true;
        break;
      }
    }

    if (mounted) {
      setState(() {
        _microphoneEnabled = hasAudio;
        if (hasAudio) {
          _microphoneState = 'On';
          _microphoneErrorMessage = null;
        } else if (_microphoneState == 'Enabling' || _microphoneState == 'On') {
          _microphoneState = 'Off';
        }

        _cameraEnabled = hasVideo;
        if (hasVideo) {
          _cameraState = 'On';
          _cameraErrorMessage = null;
        } else if (_cameraState == 'Enabling' || _cameraState == 'On') {
          _cameraState = 'Off';
        }
      });
    }
  }

  _DeviceErrorInfo _classifyDeviceError(dynamic error, String deviceType) {
    final str = error.toString().toLowerCase();

    if (str.contains('notallowederror') ||
        str.contains('permissiondenied') ||
        str.contains('permission denied') ||
        str.contains('notallowed') ||
        str.contains('blocked')) {
      return _DeviceErrorInfo(
        state: 'Permission Denied',
        userMessage: '$deviceType access is blocked. Please allow $deviceType access in your browser settings and try again.',
      );
    }

    if (str.contains('notfounderror') ||
        str.contains('devicesnotfounderror') ||
        str.contains('no camera') ||
        str.contains('no microphone') ||
        str.contains('notfound')) {
      return _DeviceErrorInfo(
        state: 'No Device',
        userMessage: 'No $deviceType was found on this device.',
      );
    }

    if (str.contains('notreadableerror') ||
        str.contains('trackstarterror') ||
        str.contains('in use') ||
        str.contains('already in use') ||
        str.contains('notreadable')) {
      return _DeviceErrorInfo(
        state: 'In Use',
        userMessage: '$deviceType is currently being used by another application. Close the other application and try again.',
      );
    }

    final cleanMsg = error.toString().replaceFirst(RegExp(r'^[A-Za-z]+Exception:\s*'), '');
    return _DeviceErrorInfo(
      state: 'Failed',
      userMessage: '$deviceType unavailable: $cleanMsg',
    );
  }

  Future<void> _toggleMicrophone() async {
    final room = _room;
    if (room == null || room.localParticipant == null) return;

    if (_microphoneEnabled) {
      try {
        await room.localParticipant!.setMicrophoneEnabled(false);
        setState(() {
          _microphoneEnabled = false;
          _microphoneState = 'Off';
        });
      } catch (e) {
        debugPrint('[MeetingRoomScreen] Failed to disable microphone: $e');
      }
    } else {
      await _initMicrophone();
    }
  }

  Future<void> _toggleCamera() async {
    final room = _room;
    if (room == null || room.localParticipant == null) return;

    if (_cameraEnabled) {
      try {
        await room.localParticipant!.setCameraEnabled(false);
        setState(() {
          _cameraEnabled = false;
          _cameraState = 'Off';
        });
      } catch (e) {
        debugPrint('[MeetingRoomScreen] Failed to disable camera: $e');
      }
    } else {
      await _initCamera();
    }
  }

  Future<void> _toggleScreenShare() async {
    final next = !_screenShareEnabled;
    try {
      await _room?.localParticipant?.setScreenShareEnabled(next);
      setState(() => _screenShareEnabled = next);
    } catch (e) {
      debugPrint('[MeetingRoomScreen] Screen share error: $e');
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('Screen sharing failed: ${e.toString().replaceFirst(RegExp(r'^[A-Za-z]+Exception:\s*'), '')}'),
            backgroundColor: const Color(0xFFDC2626),
          ),
        );
      }
    }
  }

  Future<void> _leaveMeeting() async {
    if (_isLeaving) return;
    setState(() => _isLeaving = true);
    await _recordLeave();
    await _room?.disconnect();
    if (mounted) Navigator.of(context).maybePop();
  }

  void _refresh() {
    if (mounted) setState(() {});
  }

  List<Participant> get _participants {
    final room = _room;
    if (room == null) return [];
    return [
      if (room.localParticipant != null) room.localParticipant!,
      ...room.remoteParticipants.values,
    ];
  }

  Widget _buildDeviceWarningBanner() {
    final messages = <String>[];
    if (_cameraErrorMessage != null) messages.add(_cameraErrorMessage!);
    if (_microphoneErrorMessage != null) messages.add(_microphoneErrorMessage!);
    if (messages.isEmpty) return const SizedBox.shrink();

    return Container(
      width: double.infinity,
      color: const Color(0xFF7F1D1D),
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
      child: Row(
        children: [
          const Icon(Icons.warning_amber_rounded, color: Color(0xFFFCA5A5), size: 18),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              messages.join(' '),
              style: const TextStyle(color: Colors.white, fontSize: 12, fontWeight: FontWeight.w500),
            ),
          ),
          const SizedBox(width: 8),
          if (_cameraErrorMessage != null)
            TextButton(
              style: TextButton.styleFrom(
                foregroundColor: Colors.white,
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                minimumSize: Size.zero,
                tapTargetSize: MaterialTapTargetSize.shrinkWrap,
              ),
              onPressed: _initCamera,
              child: const Text('Retry Cam', style: TextStyle(fontWeight: FontWeight.bold, fontSize: 12)),
            ),
          if (_microphoneErrorMessage != null)
            TextButton(
              style: TextButton.styleFrom(
                foregroundColor: Colors.white,
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                minimumSize: Size.zero,
                tapTargetSize: MaterialTapTargetSize.shrinkWrap,
              ),
              onPressed: _initMicrophone,
              child: const Text('Retry Mic', style: TextStyle(fontWeight: FontWeight.bold, fontSize: 12)),
            ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return PopScope(
      canPop: false,
      onPopInvokedWithResult: (didPop, result) {
        if (!didPop) _leaveMeeting();
      },
      child: Scaffold(
        backgroundColor: const Color(0xFF0F172A),
        body: Column(
          children: [
            // Top bar
            _buildTopBar(),
            // Device warning banner if permissions/devices failed
            _buildDeviceWarningBanner(),
            // Main content
            Expanded(
              child: _isConnecting ? _buildConnecting() : _buildRoom(),
            ),
            // Bottom controls
            _buildControls(),
          ],
        ),
      ),
    );
  }

  Widget _buildTopBar() {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 12),
      decoration: const BoxDecoration(
        color: Color(0xFF1E293B),
        border: Border(bottom: BorderSide(color: Color(0xFF334155))),
      ),
      child: SafeArea(
        bottom: false,
        child: Row(
          children: [
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                mainAxisSize: MainAxisSize.min,
                children: [
                  Text(
                    widget.meetingTitle,
                    style: const TextStyle(
                      color: Colors.white,
                      fontSize: 16,
                      fontWeight: FontWeight.w600,
                    ),
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                  ),
                  if (_inviteCode != null && _inviteCode!.isNotEmpty)
                    GestureDetector(
                      onTap: () {
                        Clipboard.setData(ClipboardData(text: _inviteCode!));
                        ScaffoldMessenger.of(context).showSnackBar(
                          SnackBar(content: Text('Invite code copied: $_inviteCode')),
                        );
                      },
                      child: Row(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Text(
                            _inviteCode!,
                            style: const TextStyle(
                              color: Color(0xFF94A3B8),
                              fontSize: 12,
                              fontWeight: FontWeight.w500,
                            ),
                          ),
                          const SizedBox(width: 4),
                          const Icon(Icons.copy, size: 12, color: Color(0xFF94A3B8)),
                        ],
                      ),
                    ),
                ],
              ),
            ),

            // Timer
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
              decoration: BoxDecoration(
                color: const Color(0xFF334155),
                borderRadius: BorderRadius.circular(8),
              ),
              child: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Container(
                    width: 8,
                    height: 8,
                    decoration: BoxDecoration(
                      color: _connectionStatus == 'Connected'
                          ? const Color(0xFF10B981)
                          : const Color(0xFFF59E0B),
                      shape: BoxShape.circle,
                    ),
                  ),
                  const SizedBox(width: 8),
                  Text(
                    _formatDuration(_elapsed),
                    style: const TextStyle(
                      color: Colors.white,
                      fontSize: 14,
                      fontWeight: FontWeight.w600,
                      fontFamily: 'monospace',
                    ),
                  ),
                ],
              ),
            ),

            const SizedBox(width: 12),

            // Participant count
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
              decoration: BoxDecoration(
                color: const Color(0xFF334155),
                borderRadius: BorderRadius.circular(8),
              ),
              child: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  const Icon(Icons.people_outline, size: 16, color: Color(0xFF94A3B8)),
                  const SizedBox(width: 4),
                  Text(
                    '${_participants.length}',
                    style: const TextStyle(color: Colors.white, fontSize: 13),
                  ),
                ],
              ),
            ),

            const SizedBox(width: 12),

            // Leave button
            FilledButton.icon(
              style: FilledButton.styleFrom(
                backgroundColor: const Color(0xFFEF4444),
                padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
                shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
              ),
              onPressed: _isLeaving ? null : _leaveMeeting,
              icon: const Icon(Icons.call_end, size: 18),
              label: const Text('Leave', style: TextStyle(fontWeight: FontWeight.w600)),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildConnecting() {
    if (_errorMessage != null) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(32),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Container(
                padding: const EdgeInsets.all(16),
                decoration: const BoxDecoration(
                  color: Color(0xFF7F1D1D),
                  shape: BoxShape.circle,
                ),
                child: const Icon(Icons.error_outline, size: 40, color: Color(0xFFFCA5A5)),
              ),
              const SizedBox(height: 20),
              const Text(
                'Connection Failed',
                style: TextStyle(color: Colors.white, fontSize: 20, fontWeight: FontWeight.bold),
              ),
              const SizedBox(height: 8),
              Text(
                _errorMessage!,
                textAlign: TextAlign.center,
                style: const TextStyle(color: Color(0xFF94A3B8), fontSize: 14),
              ),
              const SizedBox(height: 24),
              Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  OutlinedButton(
                    style: OutlinedButton.styleFrom(
                      foregroundColor: Colors.white,
                      side: const BorderSide(color: Color(0xFF475569)),
                    ),
                    onPressed: () => Navigator.of(context).maybePop(),
                    child: const Text('Go Back'),
                  ),
                  const SizedBox(width: 12),
                  FilledButton.icon(
                    style: FilledButton.styleFrom(backgroundColor: const Color(0xFFFF5722)),
                    onPressed: _connect,
                    icon: const Icon(Icons.refresh, size: 18),
                    label: const Text('Retry'),
                  ),
                ],
              ),
            ],
          ),
        ),
      );
    }
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          const SizedBox(
            width: 48,
            height: 48,
            child: CircularProgressIndicator(
              color: Color(0xFFFF5722),
              strokeWidth: 3,
            ),
          ),
          const SizedBox(height: 20),
          Text(
            _connectionStatus,
            style: const TextStyle(color: Colors.white, fontSize: 16),
          ),
          const SizedBox(height: 8),
          Text(
            widget.meetingTitle,
            style: const TextStyle(color: Color(0xFF94A3B8), fontSize: 13),
          ),
        ],
      ),
    );
  }

  Widget _buildRoom() {
    return Column(
      children: [
        if (_screenShareEnabled)
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
            color: const Color(0xFF1E2023),
            child: Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
                  decoration: BoxDecoration(
                    color: Colors.white.withOpacity(0.12),
                    borderRadius: BorderRadius.circular(8),
                  ),
                  child: const Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Icon(Icons.screen_share, size: 16, color: Color(0xFF8AB4F8)),
                      SizedBox(width: 8),
                      Text(
                        'You are presenting to everyone',
                        style: TextStyle(color: Colors.white, fontSize: 13, fontWeight: FontWeight.w500),
                      ),
                    ],
                  ),
                ),
                ElevatedButton(
                  style: ElevatedButton.styleFrom(
                    backgroundColor: const Color(0xFFA8C7FA),
                    foregroundColor: const Color(0xFF040E25),
                    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
                    padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
                  ),
                  onPressed: _toggleScreenShare,
                  child: const Text('Stop presenting', style: TextStyle(fontWeight: FontWeight.bold, fontSize: 12)),
                ),
              ],
            ),
          ),
        Expanded(
          child: _ParticipantGrid(
            participants: _participants,
            isScreenSharing: _screenShareEnabled,
            pinnedParticipant: _pinnedParticipant,
            onPinToggle: (p) {
              setState(() {
                if (_pinnedParticipant == p) {
                  _pinnedParticipant = null;
                } else {
                  _pinnedParticipant = p;
                }
              });
            },
          ),
        ),
      ],
    );
  }

  Widget _buildControls() {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 14),
      decoration: const BoxDecoration(
        color: Color(0xFF1E293B),
        border: Border(top: BorderSide(color: Color(0xFF334155))),
      ),
      child: SafeArea(
        top: false,
        child: Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            _ControlButton(
              icon: _microphoneEnabled ? Icons.mic : Icons.mic_off,
              label: _microphoneEnabled ? 'Mute' : 'Unmute',
              isActive: _microphoneEnabled,
              isDestructive: !_microphoneEnabled,
              onPressed: _room == null ? null : _toggleMicrophone,
            ),
            const SizedBox(width: 12),
            _ControlButton(
              icon: _cameraEnabled ? Icons.videocam : Icons.videocam_off,
              label: _cameraEnabled ? 'Camera' : 'Camera Off',
              isActive: _cameraEnabled,
              isDestructive: !_cameraEnabled,
              onPressed: _room == null ? null : _toggleCamera,
            ),
            const SizedBox(width: 12),
            _ControlButton(
              icon: _screenShareEnabled ? Icons.stop_screen_share : Icons.screen_share,
              label: _screenShareEnabled ? 'Stop Share' : 'Screen',
              isActive: !_screenShareEnabled,
              isDestructive: _screenShareEnabled,
              onPressed: _room == null ? null : _toggleScreenShare,
            ),
            if (widget.isHost) ...[
              const SizedBox(width: 12),
              _ControlButton(
                icon: Icons.more_horiz,
                label: 'More',
                isActive: true,
                onPressed: () => _showHostControls(context),
              ),
            ],
            const SizedBox(width: 24),
            if (widget.isHost)
              FilledButton.icon(
                style: FilledButton.styleFrom(
                  backgroundColor: const Color(0xFFEF4444),
                  padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 12),
                  shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                ),
                onPressed: _isLeaving ? null : () => _showHostControls(context),
                icon: const Icon(Icons.call_end, size: 20),
                label: const Text('End Meeting', style: TextStyle(fontWeight: FontWeight.w600)),
              ),
          ],
        ),
      ),
    );
  }

  Future<void> _endMeeting() async {
    if (_isLeaving) return;
    setState(() => _isLeaving = true);
    try {
      final response = await http.post(
        Uri.parse('${widget.apiBaseUrl}/meetings/${widget.meetingId}/end'),
        headers: _headers,
      );
      if (response.statusCode == 200) {
        await _recordLeave();
        await _room?.disconnect();
        if (mounted) Navigator.of(context).maybePop();
      } else {
        setState(() {
          _isLeaving = false;
          _errorMessage = 'Failed to end meeting: ${response.statusCode}';
        });
      }
    } catch (e) {
      setState(() {
        _isLeaving = false;
        _errorMessage = 'Failed to end meeting: $e';
      });
    }
  }

  void _showHostControls(BuildContext context) {
    showModalBottomSheet(
      context: context,
      backgroundColor: const Color(0xFF1E293B),
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(16)),
      ),
      builder: (context) => SafeArea(
        child: Padding(
          padding: const EdgeInsets.symmetric(vertical: 8),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Container(
                width: 40,
                height: 4,
                decoration: BoxDecoration(
                  color: const Color(0xFF475569),
                  borderRadius: BorderRadius.circular(2),
                ),
              ),
              const SizedBox(height: 16),
              const Text(
                'Host Controls',
                style: TextStyle(
                  color: Colors.white,
                  fontSize: 16,
                  fontWeight: FontWeight.bold,
                ),
              ),
              const SizedBox(height: 8),
              if (_inviteCode != null && _inviteCode!.isNotEmpty)
                ListTile(
                  leading: const Icon(Icons.share, color: Color(0xFF94A3B8)),
                  title: Text('Share invite code: $_inviteCode',
                    style: const TextStyle(color: Colors.white)),
                  onTap: () {
                    Clipboard.setData(ClipboardData(text: _inviteCode!));
                    Navigator.pop(context);
                    ScaffoldMessenger.of(context).showSnackBar(
                      SnackBar(content: Text('Invite code copied: $_inviteCode')),
                    );
                  },
                ),
              ListTile(
                leading: const Icon(Icons.cancel, color: Color(0xFFEF4444)),
                title: const Text('End Meeting for Everyone',
                  style: TextStyle(color: Color(0xFFEF4444), fontWeight: FontWeight.w600)),
                onTap: () {
                  Navigator.pop(context);
                  _endMeeting();
                },
              ),
            ],
          ),
        ),
      ),
    );
  }

  String _formatDuration(Duration duration) {
    final hours = duration.inHours;
    final minutes = duration.inMinutes.remainder(60).toString().padLeft(2, '0');
    final seconds = duration.inSeconds.remainder(60).toString().padLeft(2, '0');
    return hours > 0 ? '$hours:$minutes:$seconds' : '$minutes:$seconds';
  }
}

class _ControlButton extends StatelessWidget {
  final IconData icon;
  final String label;
  final bool isActive;
  final bool isDestructive;
  final VoidCallback? onPressed;

  const _ControlButton({
    required this.icon,
    required this.label,
    this.isActive = true,
    this.isDestructive = false,
    this.onPressed,
  });

  @override
  Widget build(BuildContext context) {
    final bgColor = isDestructive
        ? const Color(0xFFEF4444)
        : (isActive ? const Color(0xFF2563EB) : const Color(0xFF334155));
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        Material(
          color: bgColor,
          shape: const CircleBorder(),
          clipBehavior: Clip.antiAlias,
          child: InkWell(
            onTap: onPressed,
            child: Padding(
              padding: const EdgeInsets.all(14),
              child: Icon(icon, color: Colors.white, size: 22),
            ),
          ),
        ),
        const SizedBox(height: 4),
        Text(
          label,
          style: const TextStyle(color: Color(0xFF94A3B8), fontSize: 11),
        ),
      ],
    );
  }
}

class _ParticipantGrid extends StatelessWidget {
  final List<Participant> participants;
  final bool isScreenSharing;
  final Participant? pinnedParticipant;
  final ValueChanged<Participant> onPinToggle;

  const _ParticipantGrid({
    required this.participants,
    this.isScreenSharing = false,
    this.pinnedParticipant,
    required this.onPinToggle,
  });

  @override
  Widget build(BuildContext context) {
    if (participants.isEmpty) {
      return const Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.people_outline, size: 48, color: Color(0xFF475569)),
            SizedBox(height: 12),
            Text(
              'Waiting for participants...',
              style: TextStyle(color: Color(0xFF94A3B8), fontSize: 15),
            ),
          ],
        ),
      );
    }

    final bool isStageMode = isScreenSharing || pinnedParticipant != null;

    if (isStageMode) {
      final stageParticipant = pinnedParticipant ?? participants.first;
      final sidebarParticipants = participants.where((p) => p != stageParticipant).toList();

      return Padding(
        padding: const EdgeInsets.all(12),
        child: Row(
          children: [
            Expanded(
              child: _ParticipantTile(
                participant: stageParticipant,
                isPinned: pinnedParticipant == stageParticipant,
                onPinToggle: () => onPinToggle(stageParticipant),
              ),
            ),
            if (sidebarParticipants.isNotEmpty) ...[
              const SizedBox(width: 12),
              SizedBox(
                width: 240,
                child: ListView.separated(
                  itemCount: sidebarParticipants.length,
                  separatorBuilder: (_, __) => const SizedBox(height: 10),
                  itemBuilder: (context, index) {
                    final p = sidebarParticipants[index];
                    return SizedBox(
                      height: 150,
                      child: _ParticipantTile(
                        participant: p,
                        isPinned: pinnedParticipant == p,
                        onPinToggle: () => onPinToggle(p),
                      ),
                    );
                  },
                ),
              ),
            ],
          ],
        ),
      );
    }

    return LayoutBuilder(
      builder: (context, constraints) {
        final count = participants.length;
        int columns = count == 1 ? 1 : (count <= 4 ? 2 : (constraints.maxWidth > 1000 ? 3 : 2));
        return GridView.builder(
          padding: const EdgeInsets.all(12),
          gridDelegate: SliverGridDelegateWithFixedCrossAxisCount(
            crossAxisCount: columns,
            mainAxisSpacing: 10,
            crossAxisSpacing: 10,
            childAspectRatio: 16 / 10,
          ),
          itemCount: participants.length,
          itemBuilder: (context, index) {
            final p = participants[index];
            return _ParticipantTile(
              participant: p,
              isPinned: pinnedParticipant == p,
              onPinToggle: () => onPinToggle(p),
            );
          },
        );
      },
    );
  }
}

class _ParticipantTile extends StatelessWidget {
  final Participant participant;
  final bool isPinned;
  final VoidCallback? onPinToggle;

  const _ParticipantTile({
    required this.participant,
    this.isPinned = false,
    this.onPinToggle,
  });

  @override
  Widget build(BuildContext context) {
    TrackPublication? publication;
    for (final candidate in participant.videoTrackPublications) {
      final isLocal = participant is LocalParticipant;
      if (candidate.kind == TrackType.VIDEO && !candidate.muted && (isLocal || candidate.subscribed)) {
        publication = candidate;
        break;
      }
    }
    final track = publication?.track;
    final displayName = participant.name.isEmpty ? participant.identity : participant.name;

    bool isMuted = true;
    for (final pub in participant.audioTrackPublications) {
      if (pub.kind == TrackType.AUDIO && !pub.muted) {
        isMuted = false;
        break;
      }
    }

    return ClipRRect(
      borderRadius: BorderRadius.circular(12),
      child: Container(
        color: const Color(0xFF1E293B),
        child: Stack(
          fit: StackFit.expand,
          children: [
            if (track is VideoTrack)
              VideoTrackRenderer(
                track,
                fit: RTCVideoViewObjectFit.RTCVideoViewObjectFitCover,
                mirrorMode: (participant is LocalParticipant && publication?.source != TrackSource.screenShareVideo)
                    ? VideoViewMirrorMode.mirror
                    : VideoViewMirrorMode.off,
              )
            else
              Center(
                child: CircleAvatar(
                  radius: 36,
                  backgroundColor: const Color(0xFF334155),
                  child: Text(
                    _initials(displayName),
                    style: const TextStyle(
                      color: Colors.white,
                      fontSize: 24,
                      fontWeight: FontWeight.bold,
                    ),
                  ),
                ),
              ),
            if (onPinToggle != null)
              Positioned(
                top: 10,
                left: 10,
                child: InkWell(
                  onTap: onPinToggle,
                  child: Container(
                    padding: const EdgeInsets.all(6),
                    decoration: BoxDecoration(
                      color: isPinned ? const Color(0xFF2563EB) : Colors.black.withOpacity(0.6),
                      shape: BoxShape.circle,
                    ),
                    child: Icon(
                      isPinned ? Icons.push_pin : Icons.push_pin_outlined,
                      size: 16,
                      color: Colors.white,
                    ),
                  ),
                ),
              ),
            Positioned(
              left: 10,
              right: 10,
              bottom: 10,
              child: Row(
                children: [
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
                    decoration: BoxDecoration(
                      color: Colors.black.withOpacity(0.6),
                      borderRadius: BorderRadius.circular(8),
                    ),
                    child: Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Icon(
                          isMuted ? Icons.mic_off : Icons.mic,
                          size: 14,
                          color: isMuted ? const Color(0xFFEF4444) : const Color(0xFF10B981),
                        ),
                        const SizedBox(width: 6),
                        Text(
                          displayName,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: const TextStyle(color: Colors.white, fontSize: 13),
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  String _initials(String value) {
    final parts = value.trim().split(RegExp(r'\s+')).where((part) => part.isNotEmpty).toList();
    if (parts.isEmpty) return '?';
    return parts.take(2).map((part) => part[0].toUpperCase()).join();
  }
}

class _MeetingConnection {
  final String livekitUrl;
  final String token;
  final String roomName;

  const _MeetingConnection({
    required this.livekitUrl,
    required this.token,
    required this.roomName,
  });

  factory _MeetingConnection.fromJson(Map<String, dynamic> json) {
    return _MeetingConnection(
      livekitUrl: json['livekit_url'],
      token: json['token'],
      roomName: json['room_name'] ?? '',
    );
  }
}

