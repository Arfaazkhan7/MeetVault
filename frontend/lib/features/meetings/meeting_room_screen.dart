import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:livekit_client/livekit_client.dart';

import '../../core/services/api_service.dart';

class MeetingRoomScreen extends StatefulWidget {
  final String meetingId;
  final String meetingTitle;
  final String authToken;
  final String apiBaseUrl;
  final bool isHost;
  final String? livekitUrl;
  final String? token;
  final String? roomName;

  const MeetingRoomScreen({
    super.key,
    required this.meetingId,
    required this.meetingTitle,
    required this.authToken,
    this.apiBaseUrl = ApiService.baseUrl,
    this.isHost = false,
    this.livekitUrl,
    this.token,
    this.roomName,
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

  @override
  void initState() {
    super.initState();
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
        // Use pre-fetched connection details (from invite code join)
        livekitUrl = widget.livekitUrl!;
        token = widget.token!;
        roomName = widget.roomName!;
      } else {
        // Fall back to API call (for direct meeting room access)
        final connection = await _requestConnection();
        livekitUrl = connection.livekitUrl;
        token = connection.token;
        roomName = connection.roomName; // Fall back to API provided roomName
      }

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
      setState(() {
        _isConnecting = false;
        _connectionStatus = 'Failed';
        _errorMessage = error.toString();
      });
    }
  }

  Future<_MeetingConnection> _requestConnection() async {
    final response = await http.post(
      Uri.parse('${widget.apiBaseUrl}/meetings/${widget.meetingId}/room/connect'),
      headers: _headers,
    ).timeout(const Duration(seconds: 20));
    if (response.statusCode != 200) {
      throw Exception('Unable to enter meeting (${response.statusCode})');
    }
    return _MeetingConnection.fromJson(json.decode(response.body));
  }

  Future<void> _recordJoin() async {
    final response = await http.post(
      Uri.parse('${widget.apiBaseUrl}/meetings/${widget.meetingId}/room/join'),
      headers: _headers,
    ).timeout(const Duration(seconds: 20));
    if (response.statusCode != 200) {
      throw Exception('Unable to record joining time (${response.statusCode})');
    }
  }

  Future<void> _recordLeave() async {
    await http.post(
      Uri.parse('${widget.apiBaseUrl}/meetings/${widget.meetingId}/room/leave'),
      headers: _headers,
    );
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
        appBar: AppBar(
          title: Text(widget.meetingTitle),
          actions: [
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16),
              child: Center(child: Text(_formatDuration(_elapsed))),
            ),
          ],
        ),
        body: _isConnecting ? _buildConnecting() : _buildRoom(),
        bottomNavigationBar: _buildControls(),
      ),
    );
  }

  Widget _buildConnecting() {
    if (_errorMessage != null) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Icon(Icons.error_outline, size: 40),
              const SizedBox(height: 12),
              Text(_errorMessage!, textAlign: TextAlign.center),
              const SizedBox(height: 16),
              FilledButton(onPressed: _connect, child: const Text('Retry')),
            ],
          ),
        ),
      );
    }
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          const CircularProgressIndicator(),
          const SizedBox(height: 16),
          Text(_connectionStatus),
        ],
      ),
    );
  }

  Widget _buildRoom() {
    return LayoutBuilder(
      builder: (context, constraints) {
        final compact = constraints.maxWidth < 720;
        if (compact) {
          return Column(
            children: [
              Expanded(child: _ParticipantGrid(participants: _participants)),
              SizedBox(
                height: 112,
                child: _ParticipantPanel(
                  participants: _participants,
                  status: _connectionStatus,
                  isHost: widget.isHost,
                ),
              ),
            ],
          );
        }
        return Row(
          children: [
            Expanded(child: _ParticipantGrid(participants: _participants)),
            SizedBox(
              width: 280,
              child: _ParticipantPanel(
                participants: _participants,
                status: _connectionStatus,
                isHost: widget.isHost,
              ),
            ),
          ],
        );
      },
    );
  }

  Widget _buildControls() {
    return SafeArea(
      child: Container(
        padding: const EdgeInsets.all(12),
        color: Theme.of(context).colorScheme.surface,
        child: Wrap(
          alignment: WrapAlignment.center,
          spacing: 10,
          runSpacing: 10,
          children: [
            IconButton.filledTonal(
              tooltip: _microphoneEnabled ? 'Mute' : 'Unmute',
              onPressed: _room == null ? null : _toggleMicrophone,
              icon: Icon(_microphoneEnabled ? Icons.mic : Icons.mic_off),
            ),
            IconButton.filledTonal(
              tooltip: _cameraEnabled ? 'Camera off' : 'Camera on',
              onPressed: _room == null ? null : _toggleCamera,
              icon: Icon(_cameraEnabled ? Icons.videocam : Icons.videocam_off),
            ),
            IconButton.filledTonal(
              tooltip: _screenShareEnabled ? 'Stop sharing' : 'Share screen',
              onPressed: _room == null ? null : _toggleScreenShare,
              icon: Icon(_screenShareEnabled ? Icons.stop_screen_share : Icons.screen_share),
            ),
            if (widget.isHost)
              IconButton.filledTonal(
                tooltip: 'Host controls',
                onPressed: () => _showHostControls(context),
                icon: const Icon(Icons.admin_panel_settings),
              ),
            FilledButton.icon(
              onPressed: _isLeaving ? null : _leaveMeeting,
              icon: const Icon(Icons.call_end),
              label: const Text('Leave'),
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
      builder: (context) => SafeArea(
        child: ListView(
          shrinkWrap: true,
          children: [
            const ListTile(
              leading: Icon(Icons.people),
              title: Text('Manage participants'),
            ),
            const ListTile(
              leading: Icon(Icons.volume_off),
              title: Text('Mute participant'),
            ),
            const ListTile(
              leading: Icon(Icons.person_remove),
              title: Text('Remove participant'),
            ),
            ListTile(
              leading: const Icon(Icons.cancel, color: Colors.red),
              title: const Text('End Meeting', style: TextStyle(color: Colors.red)),
              onTap: () {
                Navigator.pop(context);
                _endMeeting();
              },
            ),
          ],
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

class _ParticipantGrid extends StatelessWidget {
  final List<Participant> participants;

  const _ParticipantGrid({required this.participants});

  @override
  Widget build(BuildContext context) {
    if (participants.isEmpty) {
      return const Center(child: Text('Waiting for participants'));
    }
    return LayoutBuilder(
      builder: (context, constraints) {
        final columns = constraints.maxWidth > 1000
            ? 3
            : constraints.maxWidth > 620
                ? 2
                : 1;
        return GridView.builder(
          padding: const EdgeInsets.all(12),
          gridDelegate: SliverGridDelegateWithFixedCrossAxisCount(
            crossAxisCount: columns,
            mainAxisSpacing: 12,
            crossAxisSpacing: 12,
            childAspectRatio: 16 / 10,
          ),
          itemCount: participants.length,
          itemBuilder: (context, index) => _ParticipantTile(participant: participants[index]),
        );
      },
    );
  }
}

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

    return ClipRRect(
      borderRadius: BorderRadius.circular(8),
      child: ColoredBox(
        color: Theme.of(context).colorScheme.surfaceContainerHighest,
        child: Stack(
          fit: StackFit.expand,
          children: [
            if (track is VideoTrack)
              VideoTrackRenderer(track)
            else
              Center(
                child: CircleAvatar(
                  radius: 32,
                  child: Text(_initials(participant.name.isEmpty ? participant.identity : participant.name)),
                ),
              ),
            Positioned(
              left: 10,
              right: 10,
              bottom: 10,
              child: DecoratedBox(
                decoration: BoxDecoration(
                  color: Colors.black.withOpacity(0.55),
                  borderRadius: BorderRadius.circular(6),
                ),
                child: Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 6),
                  child: Text(
                    participant.name.isEmpty ? participant.identity : participant.name,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(color: Colors.white),
                  ),
                ),
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

class _ParticipantPanel extends StatelessWidget {
  final List<Participant> participants;
  final String status;
  final bool isHost;

  const _ParticipantPanel({
    required this.participants,
    required this.status,
    required this.isHost,
  });

  @override
  Widget build(BuildContext context) {
    return DecoratedBox(
      decoration: BoxDecoration(
        border: Border(left: BorderSide(color: Theme.of(context).dividerColor)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          ListTile(
            leading: const Icon(Icons.wifi_tethering),
            title: Text(status),
            subtitle: Text('${participants.length} participant${participants.length == 1 ? '' : 's'}'),
          ),
          const Divider(height: 1),
          Expanded(
            child: ListView.builder(
              itemCount: participants.length,
              itemBuilder: (context, index) {
                final participant = participants[index];
                final displayName = participant.name.isEmpty ? participant.identity : participant.name;
                return ListTile(
                  leading: const CircleAvatar(child: Icon(Icons.person)),
                  title: Text(displayName, maxLines: 1, overflow: TextOverflow.ellipsis),
                  trailing: isHost ? const Icon(Icons.more_vert) : null,
                );
              },
            ),
          ),
        ],
      ),
    );
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
