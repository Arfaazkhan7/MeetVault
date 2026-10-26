import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';

import '../../core/navigation/app_router.dart';
import '../../core/services/api_service.dart';

class TranscriptSegment {
  final String? segmentId;
  final String? recordingId;
  final String speakerLabel;
  final String? speakerUserId;
  final String? userId;
  final String? participantId;
  final String attributionStatus;
  final double startTime;
  final double endTime;
  final String text;
  final String? translatedText;
  final String? language;
  final double? confidence;
  final String? userName; // Mapped user name if available
  final bool speakerConfirmed; // Whether speaker mapping is confirmed

  TranscriptSegment({
    this.segmentId,
    this.recordingId,
    required this.speakerLabel,
    this.speakerUserId,
    this.userId,
    this.participantId,
    this.attributionStatus = 'unknown',
    required this.startTime,
    required this.endTime,
    required this.text,
    this.translatedText,
    this.language,
    this.confidence,
    this.userName,
    this.speakerConfirmed = false,
  });

  bool get isConfirmed =>
      attributionStatus.toLowerCase() == 'confirmed' || speakerConfirmed;

  bool get isUnknown =>
      attributionStatus.toLowerCase() == 'unknown' ||
      attributionStatus.toLowerCase() == 'unconfirmed' ||
      (speakerUserId == null && (userName == null || userName!.trim().isEmpty));

  factory TranscriptSegment.fromJson(Map<String, dynamic> json) {
    final speakerUid = json['speaker_user_id']?.toString() ?? json['user_id']?.toString();
    final isConf = json['speaker_confirmed'] == true;
    final attrStatus = (json['attribution_status'] ?? (isConf ? 'confirmed' : 'unknown')).toString();

    return TranscriptSegment(
      segmentId: json['segment_id']?.toString() ?? json['id']?.toString(),
      recordingId: json['recording_id']?.toString(),
      speakerLabel: json['speaker_label'] ?? 'Speaker',
      speakerUserId: speakerUid,
      userId: speakerUid,
      participantId: json['participant_id']?.toString(),
      attributionStatus: attrStatus,
      startTime: (json['start_time'] is num) ? (json['start_time'] as num).toDouble() : 0.0,
      endTime: (json['end_time'] is num) ? (json['end_time'] as num).toDouble() : 0.0,
      text: json['text'] ?? '',
      translatedText: json['translated_text'],
      language: json['language'],
      confidence: (json['confidence'] is num) ? (json['confidence'] as num).toDouble() : null,
      userName: json['user_name'],
      speakerConfirmed: isConf,
    );
  }
}

class MeetingParticipantItem {
  final String? userPublicId;
  final String? participantId;
  final String name;
  final String? email;
  final String role;

  MeetingParticipantItem({
    this.userPublicId,
    this.participantId,
    required this.name,
    this.email,
    required this.role,
  });

  factory MeetingParticipantItem.fromJson(Map<String, dynamic> json) {
    final name = json['full_name']?.toString() ??
        json['display_name']?.toString() ??
        json['name']?.toString() ??
        json['email']?.toString() ??
        json['user_public_id']?.toString() ??
        'Participant';
    return MeetingParticipantItem(
      userPublicId: json['user_public_id']?.toString() ?? json['user_id']?.toString(),
      participantId: json['participant_id']?.toString() ?? json['id']?.toString(),
      name: name,
      email: json['email']?.toString(),
      role: json['role']?.toString() ?? 'ATTENDEE',
    );
  }
}

class TranscriptScreen extends StatefulWidget {
  final String meetingId;
  final String? meetingTitle;

  const TranscriptScreen({
    super.key,
    required this.meetingId,
    this.meetingTitle,
  });

  @override
  State<TranscriptScreen> createState() => _TranscriptScreenState();
}

class _TranscriptScreenState extends State<TranscriptScreen> {
  List<TranscriptSegment> _segments = [];
  List<MeetingParticipantItem> _participants = [];
  Map<String, dynamic>? _meetingMetadata;

  bool _isLoading = true;
  bool _isFetching = false;
  Timer? _pollingTimer;
  static const Duration _pollingInterval = Duration(seconds: 4);

  String? _errorMessage;
  int? _errorStatusCode;
  String _transcriptionStatus = 'unknown';
  String? _transcriptionError;

  // Speaker Filtering State
  String? _selectedSpeakerUserId; // null means 'All Speakers'
  bool _filterUnknownOnly = false;

  @override
  void initState() {
    super.initState();
    _loadTranscript();
  }

  @override
  void dispose() {
    _stopPolling();
    super.dispose();
  }

  void _startPolling() {
    if (_pollingTimer != null && _pollingTimer!.isActive) return;
    _pollingTimer = Timer.periodic(_pollingInterval, (_) {
      if (mounted && !_isFetching) {
        _loadTranscript(isPolling: true);
      }
    });
  }

  void _stopPolling() {
    _pollingTimer?.cancel();
    _pollingTimer = null;
  }

  Future<void> _loadTranscript({bool isPolling = false}) async {
    if (_isFetching) return;
    _isFetching = true;

    if (!isPolling) {
      setState(() {
        _isLoading = true;
        _errorMessage = null;
        _errorStatusCode = null;
      });
    }

    try {
      final api = ApiService();

      // 1. Fetch meeting metadata (optional, best-effort)
      if (!isPolling || _meetingMetadata == null) {
        try {
          final mtgResp = await api.get('/meetings/${widget.meetingId}');
          if (mtgResp.statusCode == 200) {
            _meetingMetadata = json.decode(mtgResp.body);
          }
        } catch (_) {}
      }

      // 2. Fetch authenticated participant list (scoped to meeting)
      if (!isPolling || _participants.isEmpty) {
        try {
          final partsResp = await api.get('/meetings/${widget.meetingId}/participants');
          if (partsResp.statusCode == 200) {
            final dynamic partsData = json.decode(partsResp.body);
            if (partsData is List) {
              _participants = partsData
                  .map((p) => MeetingParticipantItem.fromJson(p as Map<String, dynamic>))
                  .toList();
            }
          }
        } catch (_) {}
      }

      // 3. Fetch transcription processing status
      final statusResp = await api.get('/transcripts/meetings/${widget.meetingId}/status');

      if (statusResp.statusCode == 401) {
        _stopPolling();
        if (!mounted) return;
        setState(() {
          _isLoading = false;
          _errorStatusCode = 401;
          _errorMessage = 'Session expired. Please sign in again to access this transcript.';
        });
        return;
      }

      if (statusResp.statusCode == 403) {
        _stopPolling();
        if (!mounted) return;
        setState(() {
          _isLoading = false;
          _errorStatusCode = 403;
          _errorMessage = 'Access denied. You are not authorized to view this meeting transcript.';
        });
        return;
      }

      if (statusResp.statusCode == 404) {
        _stopPolling();
        if (!mounted) return;
        setState(() {
          _isLoading = false;
          _errorStatusCode = 404;
          _errorMessage = 'Meeting not found or transcript does not exist.';
        });
        return;
      }

      if (statusResp.statusCode != 200) {
        if (!mounted) return;
        setState(() {
          _isLoading = false;
          _errorStatusCode = statusResp.statusCode;
          _errorMessage = 'Failed to load transcription status (${statusResp.statusCode}).';
        });
        return;
      }

      final statusData = json.decode(statusResp.body);
      final status = (statusData['status'] ?? 'unknown').toString().toLowerCase();
      final err = statusData['error'] as String?;

      _transcriptionStatus = status;
      _transcriptionError = err;

      // Stop polling on terminal states; start/continue polling on active states
      const terminalStates = {'completed', 'failed'};
      if (terminalStates.contains(status)) {
        _stopPolling();
      } else {
        _startPolling();
      }

      // 4. Fetch the segments from the backend (always attempt fetch so saved live segments display even in progress)
      final transcriptResp = await api.get('/transcripts/meetings/${widget.meetingId}');
      if (transcriptResp.statusCode == 200) {
        final data = json.decode(transcriptResp.body);
        final rawSegments = (data['segments'] as List?) ?? [];
        final parsed = rawSegments
            .map((s) => TranscriptSegment.fromJson(s as Map<String, dynamic>))
            .toList();

        // Ensure strict chronological sorting by start time
        parsed.sort((a, b) => a.startTime.compareTo(b.startTime));

        if (!mounted) return;
        setState(() {
          _segments = parsed;
          _isLoading = false;
        });
        return;
      } else if (transcriptResp.statusCode == 401) {
        _stopPolling();
        if (!mounted) return;
        setState(() {
          _isLoading = false;
          _errorStatusCode = 401;
          _errorMessage = 'Session expired. Please sign in again.';
        });
        return;
      } else if (transcriptResp.statusCode == 403) {
        _stopPolling();
        if (!mounted) return;
        setState(() {
          _isLoading = false;
          _errorStatusCode = 403;
          _errorMessage = 'Access denied. You are not authorized to view this meeting transcript.';
        });
        return;
      } else {
        if (!mounted) return;
        setState(() {
          _isLoading = false;
          _errorStatusCode = transcriptResp.statusCode;
          _errorMessage = 'Failed to load transcript data (${transcriptResp.statusCode}).';
        });
        return;
      }
    } catch (e) {
      if (!mounted) return;
      final errStr = e.toString().toLowerCase();
      String userFriendlyMessage = 'An error occurred while loading the transcript.';
      if (errStr.contains('socket') ||
          errStr.contains('network') ||
          errStr.contains('clientexception') ||
          errStr.contains('failed host lookup') ||
          errStr.contains('connection refused')) {
        userFriendlyMessage = 'Network connection offline or unreachable. Please check your internet connection.';
      } else {
        userFriendlyMessage = e.toString().replaceFirst('Exception: ', '');
      }
      setState(() {
        _isLoading = false;
        // On background polling, do not wipe out existing segments with error card
        if (!isPolling || _segments.isEmpty) {
          _errorMessage = userFriendlyMessage;
        }
      });
    } finally {
      _isFetching = false;
    }
  }

  // ---------------------------------------------------------------------------
  // Filtering & Display Helpers
  // ---------------------------------------------------------------------------

  List<TranscriptSegment> get _filteredSegments {
    if (_filterUnknownOnly) {
      return _segments.where((s) => s.isUnknown).toList();
    }
    if (_selectedSpeakerUserId != null) {
      return _segments.where((s) => s.speakerUserId == _selectedSpeakerUserId).toList();
    }
    return _segments;
  }

  String _formatTime(double seconds) {
    if (seconds < 0) seconds = 0;
    final totalSecs = seconds.floor();
    final mins = totalSecs ~/ 60;
    final secs = totalSecs % 60;
    return '${mins.toString().padLeft(2, '0')}:${secs.toString().padLeft(2, '0')}';
  }

  String _getSpeakerDisplay(TranscriptSegment segment) {
    if (segment.userName != null && segment.userName!.trim().isNotEmpty) {
      return segment.userName!.trim();
    }
    if (segment.isUnknown) {
      return '${segment.speakerLabel} (Unconfirmed)';
    }
    return segment.speakerLabel;
  }

  Color _getConfidenceColor(double confidence) {
    if (confidence >= 0.85) return const Color(0xFF16A34A);
    if (confidence >= 0.65) return const Color(0xFFD97706);
    return const Color(0xFFDC2626);
  }

  String get _title {
    if (widget.meetingTitle != null && widget.meetingTitle!.isNotEmpty) {
      return widget.meetingTitle!;
    }
    final metaTitle = _meetingMetadata?['title'] as String?;
    if (metaTitle != null && metaTitle.isNotEmpty) {
      return metaTitle;
    }
    return 'Meeting Vault';
  }

  String? get _meetingDate {
    final raw = _meetingMetadata?['started_at'] ?? _meetingMetadata?['scheduled_start_time'];
    if (raw == null) return null;
    try {
      final dt = DateTime.parse(raw.toString()).toLocal();
      const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
      final month = months[dt.month - 1];
      final day = dt.day.toString().padLeft(2, '0');
      final hour = dt.hour.toString().padLeft(2, '0');
      final minute = dt.minute.toString().padLeft(2, '0');
      return '$month $day, ${dt.year} • $hour:$minute';
    } catch (_) {
      return raw.toString();
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFFF8FAFC),
      appBar: AppBar(
        title: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                const Icon(Icons.shield_outlined, size: 20, color: Color(0xFF2563EB)),
                const SizedBox(width: 6),
                Expanded(
                  child: Text(
                    _title,
                    style: const TextStyle(fontSize: 17, fontWeight: FontWeight.bold),
                    overflow: TextOverflow.ellipsis,
                  ),
                ),
              ],
            ),
            Text(
              'ID: ${widget.meetingId}${_meetingDate != null ? ' • $_meetingDate' : ''}',
              style: const TextStyle(fontSize: 11, color: Colors.grey),
            ),
          ],
        ),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh),
            tooltip: 'Refresh Vault',
            onPressed: _isLoading ? null : () => _loadTranscript(isPolling: false),
          ),
        ],
      ),
      body: _buildBody(),
    );
  }

  Widget _buildBody() {
    if (_isLoading) {
      return const Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            CircularProgressIndicator(strokeWidth: 3),
            SizedBox(height: 16),
            Text(
              'Loading meeting transcript...',
              style: TextStyle(fontSize: 15, color: Color(0xFF64748B), fontWeight: FontWeight.w500),
            ),
          ],
        ),
      );
    }

    // 401 Session Expired State
    if (_errorStatusCode == 401) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Container(
                padding: const EdgeInsets.all(16),
                decoration: const BoxDecoration(color: Color(0xFFFEF2F2), shape: BoxShape.circle),
                child: const Icon(Icons.lock_clock, size: 48, color: Color(0xFFDC2626)),
              ),
              const SizedBox(height: 20),
              const Text(
                'Session Expired',
                style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold, color: Color(0xFF0F172A)),
              ),
              const SizedBox(height: 8),
              Text(
                _errorMessage ?? 'Your session has expired. Please log in again to continue.',
                textAlign: TextAlign.center,
                style: const TextStyle(fontSize: 14, color: Color(0xFF64748B)),
              ),
              const SizedBox(height: 24),
              FilledButton.icon(
                onPressed: () => Navigator.pushNamedAndRemoveUntil(context, AppRouter.login, (r) => false),
                icon: const Icon(Icons.login),
                label: const Text('Go to Login'),
              ),
            ],
          ),
        ),
      );
    }

    // 403 Inaccessible Meeting State
    if (_errorStatusCode == 403) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Container(
                padding: const EdgeInsets.all(16),
                decoration: const BoxDecoration(color: Color(0xFFFFFBEB), shape: BoxShape.circle),
                child: const Icon(Icons.shield_outlined, size: 48, color: Color(0xFFD97706)),
              ),
              const SizedBox(height: 20),
              const Text(
                'Access Denied',
                style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold, color: Color(0xFF0F172A)),
              ),
              const SizedBox(height: 8),
              Text(
                _errorMessage ?? 'You do not have permission to access this meeting transcript.',
                textAlign: TextAlign.center,
                style: const TextStyle(fontSize: 14, color: Color(0xFF64748B)),
              ),
              const SizedBox(height: 24),
              OutlinedButton.icon(
                onPressed: () => Navigator.pop(context),
                icon: const Icon(Icons.arrow_back),
                label: const Text('Back to Meetings'),
              ),
            ],
          ),
        ),
      );
    }

    // General Error / Offline State with Safe Retry (only when no segments loaded)
    if (_errorMessage != null && _segments.isEmpty) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Container(
                padding: const EdgeInsets.all(16),
                decoration: const BoxDecoration(color: Color(0xFFFEF2F2), shape: BoxShape.circle),
                child: const Icon(Icons.error_outline, size: 48, color: Color(0xFFDC2626)),
              ),
              const SizedBox(height: 20),
              const Text(
                'Unable to Load Vault',
                style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold, color: Color(0xFF0F172A)),
              ),
              const SizedBox(height: 8),
              Text(
                _errorMessage!,
                textAlign: TextAlign.center,
                style: const TextStyle(fontSize: 14, color: Color(0xFF64748B)),
              ),
              const SizedBox(height: 24),
              FilledButton.icon(
                onPressed: () => _loadTranscript(isPolling: false),
                icon: const Icon(Icons.refresh),
                label: const Text('Retry'),
              ),
            ],
          ),
        ),
      );
    }

    // If segments exist, ALWAYS show the transcript with live/completed status header
    if (_segments.isNotEmpty) {
      final filtered = _filteredSegments;
      return RefreshIndicator(
        onRefresh: () => _loadTranscript(isPolling: false),
        child: Column(
          children: [
            // Status Banner (Live in progress, Complete, or Chunk Error Notice)
            _buildStatusBanner(),

            // AI Intelligence Quick Access Toolbar
            _buildAiQuickLinksBar(),

            // Speaker Filter Bar
            _buildSpeakerFilterBar(),

            // Active Filter Banner (if filtered)
            if (_selectedSpeakerUserId != null || _filterUnknownOnly)
              _buildActiveFilterBanner(),

          // Transcript Segments List
          Expanded(
            child: filtered.isEmpty
                ? Center(
                    child: Padding(
                      padding: const EdgeInsets.all(24),
                      child: Column(
                        mainAxisAlignment: MainAxisAlignment.center,
                        children: [
                          const Icon(Icons.filter_list_off, size: 36, color: Color(0xFF94A3B8)),
                          const SizedBox(height: 12),
                          const Text(
                            'No segments found for this speaker.',
                            style: TextStyle(fontSize: 15, fontWeight: FontWeight.w600, color: Color(0xFF475569)),
                          ),
                          const SizedBox(height: 12),
                          TextButton(
                            onPressed: () {
                              setState(() {
                                _selectedSpeakerUserId = null;
                                _filterUnknownOnly = false;
                              });
                            },
                            child: const Text('Show All Speakers'),
                          ),
                        ],
                      ),
                    ),
                  )
                : ListView.builder(
                    padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
                    itemCount: filtered.length,
                    itemBuilder: (context, index) {
                      final segment = filtered[index];
                      return _buildSegmentCard(segment);
                    },
                  ),
          ),
        ],
      ),
    );
  }

    // When _segments is empty, handle terminal failure, in-progress processing, and empty completed states
    if (_transcriptionStatus == 'failed') {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Container(
                padding: const EdgeInsets.all(16),
                decoration: const BoxDecoration(color: Color(0xFFFEF2F2), shape: BoxShape.circle),
                child: const Icon(Icons.error_outline, size: 48, color: Color(0xFFDC2626)),
              ),
              const SizedBox(height: 20),
              const Text(
                'Transcription Failed',
                style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold, color: Color(0xFF0F172A)),
              ),
              const SizedBox(height: 8),
              Text(
                _transcriptionError != null && _transcriptionError!.isNotEmpty
                    ? _transcriptionError!
                    : (_errorMessage ?? 'Transcription processing failed for this recording.'),
                textAlign: TextAlign.center,
                style: const TextStyle(fontSize: 14, color: Color(0xFF64748B)),
              ),
              const SizedBox(height: 24),
              FilledButton.icon(
                onPressed: () => _loadTranscript(isPolling: false),
                icon: const Icon(Icons.refresh),
                label: const Text('Retry'),
              ),
            ],
          ),
        ),
      );
    }

    if (_transcriptionStatus == 'pending' ||
        _transcriptionStatus == 'queued' ||
        _transcriptionStatus == 'processing' ||
        _transcriptionStatus == 'partial' ||
        _transcriptionStatus == 'waiting') {
      final isQueued = _transcriptionStatus == 'queued';
      final isPending = _transcriptionStatus == 'pending' || _transcriptionStatus == 'waiting';
      final title = isPending
          ? 'Waiting for Transcription'
          : isQueued
              ? 'Transcription Queued'
              : 'Transcribing Audio...';
      final subtitle = isPending
          ? 'Meeting audio is queued. Recognized transcript segments will appear here automatically.'
          : isQueued
              ? 'Recording is in queue for speech recognition processing.'
              : 'AI is actively transcribing speech. Saved segments will refresh automatically.';

      return Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Card(
            elevation: 0,
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(16),
              side: const BorderSide(color: Color(0xFFFDE68A)),
            ),
            color: const Color(0xFFFFFBEB),
            child: Padding(
              padding: const EdgeInsets.all(24),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  const SizedBox(
                    width: 48,
                    height: 48,
                    child: CircularProgressIndicator(strokeWidth: 3, color: Color(0xFFB45309)),
                  ),
                  const SizedBox(height: 20),
                  Text(
                    title,
                    style: const TextStyle(
                      fontSize: 18,
                      fontWeight: FontWeight.bold,
                      color: Color(0xFF92400E),
                    ),
                  ),
                  const SizedBox(height: 8),
                  Text(
                    subtitle,
                    textAlign: TextAlign.center,
                    style: const TextStyle(fontSize: 13, color: Color(0xFFB45309)),
                  ),
                  const SizedBox(height: 20),
                  FilledButton.tonalIcon(
                    onPressed: () => _loadTranscript(isPolling: false),
                    icon: const Icon(Icons.refresh, size: 18),
                    label: const Text('Refresh Status'),
                  ),
                ],
              ),
            ),
          ),
        ),
      );
    }

    // Completed Transcript with 0 speech detected
    return Column(
      children: [
        _buildAiQuickLinksBar(),
        Expanded(
          child: Center(
            child: Padding(
              padding: const EdgeInsets.all(24),
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  Container(
                    padding: const EdgeInsets.all(16),
                    decoration: const BoxDecoration(color: Color(0xFFF1F5F9), shape: BoxShape.circle),
                    child: const Icon(Icons.record_voice_over_outlined, size: 48, color: Color(0xFF94A3B8)),
                  ),
                  const SizedBox(height: 20),
                  const Text(
                    'No Speech Detected',
                    style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold, color: Color(0xFF0F172A)),
                  ),
                  const SizedBox(height: 8),
                  Text(
                    _transcriptionError != null && _transcriptionError!.isNotEmpty
                        ? 'Transcription completed with notice: $_transcriptionError'
                        : 'Transcription completed, but no spoken audio segments were detected for this meeting.',
                    textAlign: TextAlign.center,
                    style: const TextStyle(fontSize: 14, color: Color(0xFF64748B)),
                  ),
                  const SizedBox(height: 24),
                  OutlinedButton.icon(
                    onPressed: () => _loadTranscript(isPolling: false),
                    icon: const Icon(Icons.refresh),
                    label: const Text('Check Again'),
                  ),
                ],
              ),
            ),
          ),
        ),
      ],
    );
  }

  // ---------------------------------------------------------------------------
  // Sub-widgets
  // ---------------------------------------------------------------------------

  Widget _buildStatusBanner() {
    final isLive = _transcriptionStatus == 'partial' ||
        _transcriptionStatus == 'processing' ||
        _transcriptionStatus == 'queued' ||
        _transcriptionStatus == 'pending' ||
        _transcriptionStatus == 'waiting';

    if (isLive) {
      return Container(
        width: double.infinity,
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
        decoration: const BoxDecoration(
          color: Color(0xFFEFF6FF),
          border: Border(bottom: BorderSide(color: Color(0xFFBFDBFE))),
        ),
        child: Row(
          children: [
            const SizedBox(
              width: 14,
              height: 14,
              child: CircularProgressIndicator(
                strokeWidth: 2,
                valueColor: AlwaysStoppedAnimation<Color>(Color(0xFF2563EB)),
              ),
            ),
            const SizedBox(width: 10),
            const Expanded(
              child: Text(
                'Live transcription in progress • Auto-refreshing',
                style: TextStyle(
                  fontSize: 12,
                  fontWeight: FontWeight.w600,
                  color: Color(0xFF1E40AF),
                ),
              ),
            ),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
              decoration: BoxDecoration(
                color: const Color(0xFFDBEAFE),
                borderRadius: BorderRadius.circular(12),
              ),
              child: const Text(
                'LIVE',
                style: TextStyle(
                  fontSize: 10,
                  fontWeight: FontWeight.bold,
                  color: Color(0xFF1D4ED8),
                  letterSpacing: 0.5,
                ),
              ),
            ),
          ],
        ),
      );
    }

    if (_transcriptionStatus == 'completed') {
      return Container(
        width: double.infinity,
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 6),
        decoration: const BoxDecoration(
          color: Color(0xFFF0FDF4),
          border: Border(bottom: BorderSide(color: Color(0xFFBBF7D0))),
        ),
        child: const Row(
          children: [
            Icon(Icons.check_circle_outline, size: 14, color: Color(0xFF16A34A)),
            SizedBox(width: 8),
            Text(
              'Transcript finalized',
              style: TextStyle(
                fontSize: 12,
                fontWeight: FontWeight.w500,
                color: Color(0xFF15803D),
              ),
            ),
          ],
        ),
      );
    }

    if (_transcriptionError != null && _transcriptionError!.isNotEmpty) {
      return Container(
        width: double.infinity,
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 6),
        decoration: const BoxDecoration(
          color: Color(0xFFFFFBEB),
          border: Border(bottom: BorderSide(color: Color(0xFFFDE68A))),
        ),
        child: Row(
          children: [
            const Icon(Icons.warning_amber_rounded, size: 14, color: Color(0xFFD97706)),
            const SizedBox(width: 8),
            Expanded(
              child: Text(
                'Notice: $_transcriptionError',
                style: const TextStyle(fontSize: 12, color: Color(0xFF92400E)),
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
              ),
            ),
          ],
        ),
      );
    }

    return const SizedBox.shrink();
  }

  Widget _buildAiQuickLinksBar() {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
      decoration: const BoxDecoration(
        color: Colors.white,
        border: Border(bottom: BorderSide(color: Color(0xFFE2E8F0))),
      ),
      child: SingleChildScrollView(
        scrollDirection: Axis.horizontal,
        child: Row(
          children: [
            _buildNavChip(
              icon: Icons.summarize_outlined,
              label: 'AI Summary',
              color: const Color(0xFF7C3AED),
              onTap: () => Navigator.pushNamed(
                context,
                AppRouter.summary,
                arguments: {'id': widget.meetingId, 'title': _title},
              ),
            ),
            const SizedBox(width: 8),
            _buildNavChip(
              icon: Icons.topic_outlined,
              label: 'Topics',
              color: const Color(0xFFD97706),
              onTap: () => Navigator.pushNamed(
                context,
                AppRouter.topics,
                arguments: {'id': widget.meetingId, 'title': _title},
              ),
            ),
            const SizedBox(width: 8),
            _buildNavChip(
              icon: Icons.gavel_outlined,
              label: 'Decisions',
              color: const Color(0xFF4F46E5),
              onTap: () => Navigator.pushNamed(
                context,
                AppRouter.decisions,
                arguments: {'id': widget.meetingId, 'title': _title},
              ),
            ),
            const SizedBox(width: 8),
            _buildNavChip(
              icon: Icons.assignment_turned_in_outlined,
              label: 'Action Items',
              color: const Color(0xFF059669),
              onTap: () => Navigator.pushNamed(
                context,
                AppRouter.tasks,
                arguments: {'id': widget.meetingId, 'title': _title},
              ),
            ),
            const SizedBox(width: 8),
            _buildNavChip(
              icon: Icons.groups_outlined,
              label: 'Participants (${_participants.length})',
              color: const Color(0xFF2563EB),
              onTap: () => Navigator.pushNamed(
                context,
                AppRouter.participants,
                arguments: {'id': widget.meetingId},
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildNavChip({
    required IconData icon,
    required String label,
    required Color color,
    required VoidCallback onTap,
  }) {
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(8),
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
        decoration: BoxDecoration(
          color: color.withOpacity(0.08),
          borderRadius: BorderRadius.circular(8),
          border: Border.all(color: color.withOpacity(0.25)),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(icon, size: 14, color: color),
            const SizedBox(width: 5),
            Text(
              label,
              style: TextStyle(fontSize: 12, fontWeight: FontWeight.bold, color: color),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildSpeakerFilterBar() {
    final bool isAllSelected = _selectedSpeakerUserId == null && !_filterUnknownOnly;
    final int unknownCount = _segments.where((s) => s.isUnknown).length;

    // Collect distinct known participants from both participants endpoint and segment attributes
    final Map<String, String> speakerOptions = {};
    for (final p in _participants) {
      if (p.userPublicId != null) {
        speakerOptions[p.userPublicId!] = p.name;
      }
    }
    for (final s in _segments) {
      if (s.speakerUserId != null && !speakerOptions.containsKey(s.speakerUserId)) {
        speakerOptions[s.speakerUserId!] = s.userName ?? s.speakerLabel;
      }
    }

    return Container(
      width: double.infinity,
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
      decoration: const BoxDecoration(
        color: Colors.white,
        border: Border(bottom: BorderSide(color: Color(0xFFF1F5F9))),
      ),
      child: SingleChildScrollView(
        scrollDirection: Axis.horizontal,
        child: Row(
          children: [
            // "All Speakers" Chip
            FilterChip(
              key: const Key('filter_all_speakers'),
              label: Text('All Speakers (${_segments.length})'),
              selected: isAllSelected,
              onSelected: (selected) {
                setState(() {
                  _selectedSpeakerUserId = null;
                  _filterUnknownOnly = false;
                });
              },
              selectedColor: const Color(0xFFDBEAFE),
              checkmarkColor: const Color(0xFF1D4ED8),
              labelStyle: TextStyle(
                fontSize: 12,
                fontWeight: isAllSelected ? FontWeight.bold : FontWeight.w500,
                color: isAllSelected ? const Color(0xFF1D4ED8) : const Color(0xFF334155),
              ),
            ),
            const SizedBox(width: 8),

            // Individual Participant Filter Chips
            ...speakerOptions.entries.map((entry) {
              final speakerId = entry.key;
              final speakerName = entry.value;
              final segCount = _segments.where((s) => s.speakerUserId == speakerId).length;
              final isSelected = _selectedSpeakerUserId == speakerId;

              return Padding(
                padding: const EdgeInsets.only(right: 8),
                child: FilterChip(
                  key: Key('filter_speaker_$speakerId'),
                  avatar: const Icon(Icons.person, size: 14),
                  label: Text('$speakerName ($segCount)'),
                  selected: isSelected,
                  onSelected: (selected) {
                    setState(() {
                      _selectedSpeakerUserId = selected ? speakerId : null;
                      _filterUnknownOnly = false;
                    });
                  },
                  selectedColor: const Color(0xFFECFDF5),
                  checkmarkColor: const Color(0xFF047857),
                  labelStyle: TextStyle(
                    fontSize: 12,
                    fontWeight: isSelected ? FontWeight.bold : FontWeight.w500,
                    color: isSelected ? const Color(0xFF047857) : const Color(0xFF334155),
                  ),
                ),
              );
            }),

            // "Unconfirmed / Unknown" Chip (if present)
            if (unknownCount > 0)
              FilterChip(
                key: const Key('filter_unknown_speakers'),
                avatar: const Icon(Icons.help_outline, size: 14, color: Color(0xFFB45309)),
                label: Text('Unconfirmed ($unknownCount)'),
                selected: _filterUnknownOnly,
                onSelected: (selected) {
                  setState(() {
                    _filterUnknownOnly = selected;
                    _selectedSpeakerUserId = null;
                  });
                },
                selectedColor: const Color(0xFFFEF3C7),
                checkmarkColor: const Color(0xFFB45309),
                labelStyle: TextStyle(
                  fontSize: 12,
                  fontWeight: _filterUnknownOnly ? FontWeight.bold : FontWeight.w500,
                  color: _filterUnknownOnly ? const Color(0xFFB45309) : const Color(0xFF334155),
                ),
              ),
          ],
        ),
      ),
    );
  }

  Widget _buildActiveFilterBanner() {
    String filterLabel = 'Unknown Speakers';
    if (_selectedSpeakerUserId != null) {
      final part = _participants.firstWhere(
        (p) => p.userPublicId == _selectedSpeakerUserId,
        orElse: () => MeetingParticipantItem(name: 'Selected Speaker', role: ''),
      );
      filterLabel = part.name;
    }

    return Container(
      width: double.infinity,
      color: const Color(0xFFEFF6FF),
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 6),
      child: Row(
        children: [
          const Icon(Icons.filter_alt, size: 14, color: Color(0xFF2563EB)),
          const SizedBox(width: 6),
          Expanded(
            child: Text(
              'Showing speech by: $filterLabel (${_filteredSegments.length} segments)',
              style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w600, color: Color(0xFF1E40AF)),
            ),
          ),
          InkWell(
            onTap: () {
              setState(() {
                _selectedSpeakerUserId = null;
                _filterUnknownOnly = false;
              });
            },
            child: const Padding(
              padding: EdgeInsets.symmetric(horizontal: 4, vertical: 2),
              child: Row(
                children: [
                  Icon(Icons.close, size: 13, color: Color(0xFF1E40AF)),
                  SizedBox(width: 2),
                  Text('Show All', style: TextStyle(fontSize: 12, fontWeight: FontWeight.bold, color: Color(0xFF1E40AF))),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildSegmentCard(TranscriptSegment segment) {
    final speakerDisplay = _getSpeakerDisplay(segment);
    final isConfirmed = segment.isConfirmed;
    final hasTranslation = segment.translatedText != null &&
        segment.translatedText!.trim().isNotEmpty &&
        segment.translatedText!.trim() != segment.text.trim();

    return Card(
      margin: const EdgeInsets.only(bottom: 10),
      elevation: 0,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(12),
        side: const BorderSide(color: Color(0xFFE2E8F0)),
      ),
      color: Colors.white,
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // Header Row: Speaker Label, Status Badge, Timestamp, Confidence
            Row(
              children: [
                // Speaker Chip
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                  decoration: BoxDecoration(
                    color: isConfirmed ? const Color(0xFFECFDF5) : const Color(0xFFFFFBEB),
                    borderRadius: BorderRadius.circular(6),
                    border: Border.all(
                      color: isConfirmed ? const Color(0xFFA7F3D0) : const Color(0xFFFDE68A),
                    ),
                  ),
                  child: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Icon(
                        isConfirmed ? Icons.person : Icons.mic_none,
                        size: 13,
                        color: isConfirmed ? const Color(0xFF047857) : const Color(0xFFB45309),
                      ),
                      const SizedBox(width: 4),
                      Text(
                        speakerDisplay,
                        style: TextStyle(
                          fontSize: 12,
                          fontWeight: FontWeight.bold,
                          color: isConfirmed ? const Color(0xFF047857) : const Color(0xFFB45309),
                        ),
                      ),
                      if (isConfirmed) ...[
                        const SizedBox(width: 4),
                        const Icon(Icons.check_circle, size: 11, color: Color(0xFF047857)),
                      ],
                    ],
                  ),
                ),
                const SizedBox(width: 10),

                // Timestamp Range
                Text(
                  '${_formatTime(segment.startTime)} – ${_formatTime(segment.endTime)}',
                  style: const TextStyle(
                    fontSize: 12,
                    fontWeight: FontWeight.w600,
                    color: Color(0xFF64748B),
                  ),
                ),
                const Spacer(),

                // Detected Language Tag
                if (segment.language != null && segment.language!.isNotEmpty) ...[
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                    decoration: BoxDecoration(
                      color: const Color(0xFFF1F5F9),
                      borderRadius: BorderRadius.circular(6),
                      border: Border.all(color: const Color(0xFFCBD5E1)),
                    ),
                    child: Text(
                      segment.language!.toUpperCase(),
                      style: const TextStyle(
                        fontSize: 10,
                        fontWeight: FontWeight.bold,
                        color: Color(0xFF475569),
                      ),
                    ),
                  ),
                  const SizedBox(width: 6),
                ],

                // Confidence Percentage
                if (segment.confidence != null)
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                    decoration: BoxDecoration(
                      color: _getConfidenceColor(segment.confidence!).withOpacity(0.12),
                      borderRadius: BorderRadius.circular(6),
                      border: Border.all(
                        color: _getConfidenceColor(segment.confidence!).withOpacity(0.3),
                      ),
                    ),
                    child: Text(
                      '${(segment.confidence! * 100).toStringAsFixed(0)}%',
                      style: TextStyle(
                        fontSize: 10,
                        fontWeight: FontWeight.bold,
                        color: _getConfidenceColor(segment.confidence!),
                      ),
                    ),
                  ),
              ],
            ),
            const SizedBox(height: 10),

            // Transcript Text
            SelectableText(
              segment.text,
              style: const TextStyle(
                fontSize: 15,
                height: 1.45,
                color: Color(0xFF1E293B),
              ),
            ),

            // Optional Translated Text Callout
            if (hasTranslation) ...[
              const SizedBox(height: 10),
              Container(
                width: double.infinity,
                padding: const EdgeInsets.all(10),
                decoration: BoxDecoration(
                  color: const Color(0xFFF8FAFC),
                  borderRadius: BorderRadius.circular(8),
                  border: Border.all(color: const Color(0xFFE2E8F0)),
                ),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Icon(Icons.translate, size: 14, color: Color(0xFF64748B)),
                    const SizedBox(width: 8),
                    Expanded(
                      child: SelectableText(
                        segment.translatedText!,
                        style: const TextStyle(
                          fontSize: 14,
                          fontStyle: FontStyle.italic,
                          color: Color(0xFF334155),
                          height: 1.4,
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }
}
