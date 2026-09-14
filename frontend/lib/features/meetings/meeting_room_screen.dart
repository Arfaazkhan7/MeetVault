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

class _MeetingRoomScreenState extends State<MeetingRoomScreen> {
  Room? _room;
  EventsListener<RoomEvent>? _listener;
  Timer? _timer;
  Duration _elapsed = Duration.zero;
  DateTime? _joinedAt;
  bool _isConnecting = true;
  bool _isLeaving = false;
  bool _microphoneEnabled = true;
  bool _cameraEnabled = true;
  bool _screenShareEnabled = false;
  String _connectionStatus = 'Connecting';
  String? _errorMessage;
  String? _inviteCode;

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
        ..on<LocalTrackPublishedEvent>((event) => _refresh())
        ..on<LocalTrackUnpublishedEvent>((event) => _refresh());

      setState(() => _connectionStatus = 'Connecting to server');

      await room.connect(
        livekitUrl,
        token,
        roomOptions: const RoomOptions(
          adaptiveStream: true,
          dynacast: true,
        ),
      );
      await room.localParticipant?.setMicrophoneEnabled(true);
      await room.localParticipant?.setCameraEnabled(true);

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
    } catch (error) {
      String msg = error.toString();
      // Make LiveKit errors more human-friendly
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
    } catch (_) {
      // Non-critical: don't block room entry
    }
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

  Future<void> _toggleMicrophone() async {
    final next = !_microphoneEnabled;
    await _room?.localParticipant?.setMicrophoneEnabled(next);
    setState(() => _microphoneEnabled = next);
  }

  Future<void> _toggleCamera() async {
    final next = !_cameraEnabled;
    await _room?.localParticipant?.setCameraEnabled(next);
    setState(() => _cameraEnabled = next);
  }

  Future<void> _toggleScreenShare() async {
    final next = !_screenShareEnabled;
    await _room?.localParticipant?.setScreenShareEnabled(next);
    setState(() => _screenShareEnabled = next);
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
            // ── Top bar ──────────────────────────────────────────────
            _buildTopBar(),
            // ── Main content ─────────────────────────────────────────
            Expanded(
              child: _isConnecting ? _buildConnecting() : _buildRoom(),
            ),
            // ── Bottom controls ──────────────────────────────────────
            _buildControls(),
          ],
        ),
      ),
    );
  }

  // ── Top Bar ──────────────────────────────────────────────────────────
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
            // Meeting title
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

  // ── Connecting / Error ────────────────────────────────────────────────
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

  // ── Room View (Video Grid) ────────────────────────────────────────────
  Widget _buildRoom() {
    return _ParticipantGrid(participants: _participants);
  }

  // ── Bottom Controls Bar ───────────────────────────────────────────────
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
            // End Meeting button (host) or Leave button
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

// ── Control Button Widget ─────────────────────────────────────────────────
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
        : const Color(0xFF334155);
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

// ── Participant Grid ──────────────────────────────────────────────────────
class _ParticipantGrid extends StatelessWidget {
  final List<Participant> participants;

  const _ParticipantGrid({required this.participants});

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
    return LayoutBuilder(
      builder: (context, constraints) {
        final count = participants.length;
        int columns;
        if (count == 1) {
          columns = 1;
        } else if (count <= 4) {
          columns = 2;
        } else if (constraints.maxWidth > 1000) {
          columns = 3;
        } else {
          columns = 2;
        }
        return GridView.builder(
          padding: const EdgeInsets.all(12),
          gridDelegate: SliverGridDelegateWithFixedCrossAxisCount(
            crossAxisCount: columns,
            mainAxisSpacing: 10,
            crossAxisSpacing: 10,
            childAspectRatio: 16 / 10,
          ),
          itemCount: participants.length,
          itemBuilder: (context, index) => _ParticipantTile(participant: participants[index]),
        );
      },
    );
  }
}

// ── Participant Tile ──────────────────────────────────────────────────────
class _ParticipantTile extends StatelessWidget {
  final Participant participant;

  const _ParticipantTile({required this.participant});

  @override
  Widget build(BuildContext context) {
    TrackPublication? publication;
    for (final candidate in participant.videoTrackPublications) {
      if (candidate.kind == TrackType.VIDEO && candidate.subscribed && !candidate.muted) {
        publication = candidate;
        break;
      }
    }
    final track = publication?.track;
    final displayName = participant.name.isEmpty ? participant.identity : participant.name;

    // Check mic status
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
                mirrorMode: participant is LocalParticipant
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
            // Name badge at bottom
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
