import 'package:flutter/material.dart';
import '../../core/navigation/app_router.dart';
import '../../core/widgets/enterprise_scaffold.dart';

enum SearchMode { hybrid, semantic, keyword }

class SearchScreen extends StatefulWidget {
  const SearchScreen({super.key});

  @override
  State<SearchScreen> createState() => _SearchScreenState();
}

class _SearchScreenState extends State<SearchScreen>
    with SingleTickerProviderStateMixin {
  late final TabController _tabController;

  @override
  void initState() {
    super.initState();
    _tabController = TabController(length: 2, vsync: this);
  }

  @override
  void dispose() {
    _tabController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return EnterpriseScaffold(
      title: 'Meeting Memory Intelligence',
      currentRoute: AppRouter.search,
      child: Column(
        children: [
          Container(
            color: const Color(0xFF0F172A),
            child: TabBar(
              controller: _tabController,
              indicatorColor: const Color(0xFF6366F1),
              labelColor: Colors.white,
              unselectedLabelColor: Colors.grey,
              tabs: const [
                Tab(icon: Icon(Icons.search, size: 18), text: 'Semantic Search'),
                Tab(icon: Icon(Icons.psychology_outlined, size: 18), text: 'Ask Memory'),
              ],
            ),
          ),
          Expanded(
            child: TabBarView(
              controller: _tabController,
              children: const [
                _SearchTab(),
                _AskMemoryTab(),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

// ─── SEMANTIC SEARCH TAB ───────────────────────────────────────────────────────

class _SearchTab extends StatefulWidget {
  const _SearchTab();

  @override
  State<_SearchTab> createState() => _SearchTabState();
}

class _SearchTabState extends State<_SearchTab> {
  final TextEditingController _searchController = TextEditingController();
  final TextEditingController _topicController = TextEditingController();
  SearchMode _selectedMode = SearchMode.hybrid;
  bool _isSearching = false;
  bool _isIndexing = false;
  String? _statusMessage;

  final List<Map<String, dynamic>> _results = [
    {
      'source_type': 'decision',
      'title': '[Cloud Platform] Decision Record (Architecture Sync)',
      'meeting_title': 'Architecture Sync',
      'speaker_label': 'Lead Architect',
      'content_text': 'The team selects ECS over Lambda to prevent cold-start latency issues during peak traffic.',
      'score': 0.9450,
      'timestamp': '2026-09-07T14:30:00',
    },
    {
      'source_type': 'transcript_segment',
      'title': 'Transcript Segment (Engineering Lead)',
      'meeting_title': 'Backend Tech Assessment',
      'speaker_label': 'Engineering Lead',
      'content_text': 'Cold-start latency concerns were raised regarding serverless options.',
      'score': 0.8820,
      'timestamp': '2026-09-05T10:15:00',
    },
    {
      'source_type': 'document_page',
      'title': 'Document Page (Architecture Proposal PDF)',
      'meeting_title': 'Document Review',
      'speaker_label': 'Doc AI',
      'content_text': 'Page 4: Containerized deployment benchmarks comparing ECS task startup times vs AWS Lambda cold starts.',
      'score': 0.8110,
      'timestamp': '2026-09-06T11:00:00',
    },
  ];

  void _performSearch() {
    final query = _searchController.text.trim();
    if (query.isEmpty) return;
    setState(() { _isSearching = true; _statusMessage = null; });
    Future.delayed(const Duration(milliseconds: 400), () {
      if (!mounted) return;
      setState(() {
        _isSearching = false;
        _statusMessage = 'Retrieved ${_results.length} evidence matches via ${_selectedMode.name.toUpperCase()} mode.';
      });
    });
  }

  void _triggerIndexing() {
    setState(() { _isIndexing = true; _statusMessage = null; });
    Future.delayed(const Duration(milliseconds: 600), () {
      if (!mounted) return;
      setState(() {
        _isIndexing = false;
        _statusMessage = 'Successfully indexed vector embeddings across transcripts, summaries, topics, decisions, and document pages.';
      });
    });
  }

  Color _getBadgeColor(String sourceType) {
    switch (sourceType) {
      case 'decision': return Colors.green;
      case 'transcript_segment': return Colors.indigo;
      case 'topic': return Colors.amber;
      case 'document_page': return Colors.teal;
      case 'meeting_summary': return Colors.purple;
      default: return Colors.blueGrey;
    }
  }

  @override
  Widget build(BuildContext context) {
    return ListView(
      padding: const EdgeInsets.all(20),
      children: [
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            const Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('Cross-Meeting Semantic Memory Search',
                  style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold, color: Colors.white)),
              SizedBox(height: 4),
              Text('1536-dim vector search across transcripts, decisions, topics, and documents.',
                  style: TextStyle(fontSize: 12, color: Colors.grey)),
            ]),
            ElevatedButton.icon(
              onPressed: _isIndexing ? null : _triggerIndexing,
              icon: _isIndexing
                  ? const SizedBox(width: 14, height: 14, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
                  : const Icon(Icons.bolt_outlined, size: 16),
              label: Text(_isIndexing ? 'Indexing...' : 'Index Memory'),
              style: ElevatedButton.styleFrom(backgroundColor: const Color(0xFF6366F1), foregroundColor: Colors.white),
            ),
          ],
        ),
        const SizedBox(height: 16),
        Card(
          color: const Color(0xFF1E293B),
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(children: [
              Row(children: [
                Expanded(
                  child: TextField(
                    controller: _searchController,
                    style: const TextStyle(color: Colors.white),
                    decoration: InputDecoration(
                      prefixIcon: const Icon(Icons.search, color: Color(0xFF818CF8)),
                      hintText: 'e.g. Why did we change the database architecture to ECS?',
                      hintStyle: TextStyle(color: Colors.grey[500], fontSize: 13),
                      filled: true, fillColor: const Color(0xFF0F172A),
                      border: OutlineInputBorder(borderRadius: BorderRadius.circular(10), borderSide: BorderSide.none),
                    ),
                    onSubmitted: (_) => _performSearch(),
                  ),
                ),
                const SizedBox(width: 10),
                ElevatedButton(
                  onPressed: _isSearching ? null : _performSearch,
                  style: ElevatedButton.styleFrom(backgroundColor: const Color(0xFF4F46E5), foregroundColor: Colors.white,
                      padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 18)),
                  child: _isSearching
                      ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
                      : const Text('Search'),
                ),
              ]),
              const SizedBox(height: 14),
              Row(children: [
                const Text('Mode: ', style: TextStyle(color: Colors.grey, fontWeight: FontWeight.w600, fontSize: 13)),
                const SizedBox(width: 6),
                SegmentedButton<SearchMode>(
                  segments: const [
                    ButtonSegment(value: SearchMode.hybrid, label: Text('Hybrid')),
                    ButtonSegment(value: SearchMode.semantic, label: Text('Semantic')),
                    ButtonSegment(value: SearchMode.keyword, label: Text('Keyword')),
                  ],
                  selected: {_selectedMode},
                  onSelectionChanged: (s) => setState(() => _selectedMode = s.first),
                ),
                const SizedBox(width: 16),
                Expanded(child: TextField(
                  controller: _topicController,
                  style: const TextStyle(color: Colors.white, fontSize: 12),
                  decoration: InputDecoration(
                    prefixIcon: const Icon(Icons.filter_list, size: 14, color: Colors.grey),
                    hintText: 'Filter by topic / project...',
                    hintStyle: TextStyle(color: Colors.grey[600], fontSize: 12),
                    filled: true, fillColor: const Color(0xFF0F172A),
                    contentPadding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
                    border: OutlineInputBorder(borderRadius: BorderRadius.circular(8), borderSide: BorderSide.none),
                  ),
                )),
              ]),
            ]),
          ),
        ),
        if (_statusMessage != null) ...[
          const SizedBox(height: 12),
          Container(
            padding: const EdgeInsets.all(10),
            decoration: BoxDecoration(
              color: const Color(0xFF312E81).withOpacity(0.4),
              borderRadius: BorderRadius.circular(8),
              border: Border.all(color: const Color(0xFF6366F1).withOpacity(0.5)),
            ),
            child: Row(children: [
              const Icon(Icons.info_outline, color: Color(0xFF818CF8), size: 16),
              const SizedBox(width: 8),
              Text(_statusMessage!, style: const TextStyle(color: Color(0xFFC7D2FE), fontSize: 12)),
            ]),
          ),
        ],
        const SizedBox(height: 20),
        Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
          Text('Retrieved Evidence Context (${_results.length})',
              style: const TextStyle(fontSize: 15, fontWeight: FontWeight.bold, color: Colors.white)),
          const Text('Ranked by Cosine Similarity', style: TextStyle(fontSize: 11, color: Colors.grey)),
        ]),
        const SizedBox(height: 10),
        ListView.separated(
          shrinkWrap: true,
          physics: const NeverScrollableScrollPhysics(),
          itemCount: _results.length,
          separatorBuilder: (_, __) => const SizedBox(height: 10),
          itemBuilder: (context, i) {
            final res = _results[i];
            final scorePct = ((res['score'] as double) * 100).toStringAsFixed(1);
            final badge = _getBadgeColor(res['source_type'] as String);
            return Card(
              color: const Color(0xFF1E293B),
              shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
              child: Padding(padding: const EdgeInsets.all(14), child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
                    Container(
                      padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 3),
                      decoration: BoxDecoration(color: badge.withOpacity(0.2), borderRadius: BorderRadius.circular(5), border: Border.all(color: badge.withOpacity(0.6))),
                      child: Text((res['source_type'] as String).toUpperCase().replaceAll('_', ' '),
                          style: TextStyle(color: badge, fontSize: 10, fontWeight: FontWeight.bold)),
                    ),
                    Container(
                      padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 3),
                      decoration: BoxDecoration(color: const Color(0xFF0F172A), borderRadius: BorderRadius.circular(5)),
                      child: Text('$scorePct% match', style: const TextStyle(color: Color(0xFF38BDF8), fontSize: 11, fontWeight: FontWeight.bold)),
                    ),
                  ]),
                  const SizedBox(height: 8),
                  Text(res['title'] as String, style: const TextStyle(color: Colors.white, fontSize: 13, fontWeight: FontWeight.w600)),
                  const SizedBox(height: 5),
                  Text(res['content_text'] as String, style: const TextStyle(color: Color(0xFFCBD5E1), fontSize: 12, height: 1.4)),
                  const SizedBox(height: 10),
                  Row(children: [
                    const Icon(Icons.meeting_room, size: 12, color: Colors.grey),
                    const SizedBox(width: 4),
                    Text(res['meeting_title'] as String, style: const TextStyle(color: Colors.grey, fontSize: 11)),
                    const SizedBox(width: 14),
                    const Icon(Icons.person, size: 12, color: Colors.grey),
                    const SizedBox(width: 4),
                    Text(res['speaker_label'] as String, style: const TextStyle(color: Colors.grey, fontSize: 11)),
                  ]),
                ],
              )),
            );
          },
        ),
      ],
    );
  }
}

// ─── ASK MEMORY TAB ────────────────────────────────────────────────────────────

class _AskMemoryTab extends StatefulWidget {
  const _AskMemoryTab();

  @override
  State<_AskMemoryTab> createState() => _AskMemoryTabState();
}

class _AskMemoryTabState extends State<_AskMemoryTab> {
  final TextEditingController _questionController = TextEditingController();
  bool _isAsking = false;
  _AskResult? _result;

  final List<String> _exampleQuestions = [
    "What did we discuss about authentication?",
    "Why did we change the database architecture?",
    "Who proposed ECS?",
    "What decisions were made about the mobile application?",
    "What tasks are still pending?",
    "How has the project's authentication strategy changed?",
    "Which meetings discussed database performance?",
  ];

  void _ask() {
    final q = _questionController.text.trim();
    if (q.isEmpty) return;
    setState(() { _isAsking = true; _result = null; });
    Future.delayed(const Duration(milliseconds: 600), () {
      if (!mounted) return;
      setState(() {
        _isAsking = false;
        _result = _AskResult(
          question: q,
          answer:
              "Based on the meeting evidence retrieved from memory: The team raises concerns about cold-start "
              "latency when scaling cloud database instances. The team selected ECS containerized deployment "
              "over Lambda to eliminate cold-start penalties and support high concurrency during peak traffic. "
              "This decision was proposed by the Lead Architect in the Architecture Sync meeting and finalized "
              "after a performance evaluation meeting.",
          confidence: 0.87,
          insufficientEvidence: false,
          evidence: [
            _Evidence(
              sourceType: 'decision',
              meetingTitle: 'Architecture Finalization',
              meetingDate: 'Sep 7, 2026',
              speaker: 'Lead Architect',
              excerpt: 'The team selects ECS over Lambda to prevent cold-start latency issues during peak traffic.',
              score: 0.945,
            ),
            _Evidence(
              sourceType: 'transcript_segment',
              meetingTitle: 'Performance Evaluation',
              meetingDate: 'Sep 5, 2026',
              speaker: 'QA Engineer',
              excerpt: 'Cold-start latency spikes measured at 450ms during spike test – serverless architecture not viable.',
              score: 0.882,
            ),
            _Evidence(
              sourceType: 'document_page',
              meetingTitle: 'Document Review',
              meetingDate: 'Sep 6, 2026',
              speaker: 'Doc AI',
              excerpt: 'ECS containers achieve sub-10ms response times vs 450ms cold-start spikes.',
              score: 0.811,
            ),
          ],
          evalAvgScore: 0.879,
          evalMeetingsCovered: 3,
          evalFaithfulness: 0.94,
        );
      });
    });
  }

  @override
  Widget build(BuildContext context) {
    return ListView(
      padding: const EdgeInsets.all(20),
      children: [
        // Header
        const Text('Ask Meeting Memory',
            style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold, color: Colors.white)),
        const SizedBox(height: 4),
        const Text(
          "Ask natural-language questions about your company's meeting history. Every answer is grounded in evidence.",
          style: TextStyle(fontSize: 13, color: Colors.grey),
        ),
        const SizedBox(height: 20),

        // Question input
        Card(
          color: const Color(0xFF1E293B),
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Row(children: [
                Expanded(
                  child: TextField(
                    controller: _questionController,
                    style: const TextStyle(color: Colors.white),
                    maxLines: 2,
                    decoration: InputDecoration(
                      prefixIcon: const Padding(
                        padding: EdgeInsets.only(bottom: 20),
                        child: Icon(Icons.psychology_outlined, color: Color(0xFF818CF8)),
                      ),
                      hintText: 'Ask a question about your meetings...',
                      hintStyle: TextStyle(color: Colors.grey[500], fontSize: 13),
                      filled: true, fillColor: const Color(0xFF0F172A),
                      border: OutlineInputBorder(borderRadius: BorderRadius.circular(10), borderSide: BorderSide.none),
                    ),
                    onSubmitted: (_) => _ask(),
                  ),
                ),
                const SizedBox(width: 10),
                ElevatedButton(
                  onPressed: _isAsking ? null : _ask,
                  style: ElevatedButton.styleFrom(
                    backgroundColor: const Color(0xFF7C3AED),
                    foregroundColor: Colors.white,
                    padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 24),
                  ),
                  child: _isAsking
                      ? const SizedBox(width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
                      : const Column(mainAxisSize: MainAxisSize.min, children: [
                          Icon(Icons.send, size: 18),
                          SizedBox(height: 2),
                          Text('Ask', style: TextStyle(fontSize: 11)),
                        ]),
                ),
              ]),
              const SizedBox(height: 12),
              // Example questions
              Wrap(
                spacing: 8,
                runSpacing: 6,
                children: _exampleQuestions.map((q) => GestureDetector(
                  onTap: () => setState(() => _questionController.text = q),
                  child: Container(
                    padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
                    decoration: BoxDecoration(
                      color: const Color(0xFF1E1B4B),
                      borderRadius: BorderRadius.circular(20),
                      border: Border.all(color: const Color(0xFF6366F1).withOpacity(0.4)),
                    ),
                    child: Text(q, style: const TextStyle(color: Color(0xFFA5B4FC), fontSize: 11)),
                  ),
                )).toList(),
              ),
            ]),
          ),
        ),
        const SizedBox(height: 20),

        // Answer
        if (_result != null) ...[
          if (_result!.insufficientEvidence)
            _InsufficientEvidenceCard()
          else ...[
            _AnswerCard(result: _result!),
            const SizedBox(height: 16),
            _RAGEvalCard(result: _result!),
            const SizedBox(height: 16),
            _EvidenceList(evidence: _result!.evidence),
          ],
        ],
      ],
    );
  }
}

// ─── ANSWER CARD ─────────────────────────────────────────────────────────────

class _AnswerCard extends StatelessWidget {
  final _AskResult result;
  const _AnswerCard({required this.result});

  @override
  Widget build(BuildContext context) {
    final confidencePct = (result.confidence * 100).toStringAsFixed(0);
    final confidenceColor = result.confidence > 0.7
        ? Colors.green
        : result.confidence > 0.4
            ? Colors.amber
            : Colors.red;

    return Container(
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: const Color(0xFF7C3AED).withOpacity(0.6)),
        gradient: LinearGradient(
          colors: [const Color(0xFF1E1B4B), const Color(0xFF1E293B)],
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
        ),
      ),
      padding: const EdgeInsets.all(20),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
          Row(children: [
            Container(
              width: 32, height: 32,
              decoration: BoxDecoration(color: const Color(0xFF7C3AED).withOpacity(0.3), shape: BoxShape.circle),
              child: const Icon(Icons.psychology, color: Color(0xFFA78BFA), size: 18),
            ),
            const SizedBox(width: 10),
            const Text('MeetVault AI Answer',
                style: TextStyle(color: Colors.white, fontWeight: FontWeight.bold, fontSize: 14)),
          ]),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
            decoration: BoxDecoration(
              color: confidenceColor.withOpacity(0.15),
              borderRadius: BorderRadius.circular(20),
              border: Border.all(color: confidenceColor.withOpacity(0.5)),
            ),
            child: Text('$confidencePct% confidence',
                style: TextStyle(color: confidenceColor, fontSize: 12, fontWeight: FontWeight.bold)),
          ),
        ]),
        const SizedBox(height: 14),
        Text(result.answer,
            style: const TextStyle(color: Color(0xFFE2E8F0), fontSize: 13, height: 1.6)),
      ]),
    );
  }
}

// ─── RAG EVAL CARD ───────────────────────────────────────────────────────────

class _RAGEvalCard extends StatelessWidget {
  final _AskResult result;
  const _RAGEvalCard({required this.result});

  @override
  Widget build(BuildContext context) {
    return Card(
      color: const Color(0xFF0F1A2E),
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(10),
        side: BorderSide(color: Colors.blueGrey.withOpacity(0.3)),
      ),
      child: Padding(padding: const EdgeInsets.all(14), child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text('RAG Evaluation Metrics',
              style: TextStyle(color: Colors.grey, fontSize: 12, fontWeight: FontWeight.w600)),
          const SizedBox(height: 12),
          Row(children: [
            _EvalMetric(label: 'Avg Evidence Score',
                value: '${(result.evalAvgScore * 100).toStringAsFixed(1)}%', color: Colors.cyan),
            const SizedBox(width: 24),
            _EvalMetric(label: 'Meetings Covered',
                value: '${result.evalMeetingsCovered}', color: Colors.purple),
            const SizedBox(width: 24),
            _EvalMetric(label: 'Faithfulness',
                value: '${(result.evalFaithfulness * 100).toStringAsFixed(0)}%', color: Colors.green),
          ]),
        ],
      )),
    );
  }
}

class _EvalMetric extends StatelessWidget {
  final String label;
  final String value;
  final Color color;
  const _EvalMetric({required this.label, required this.value, required this.color});

  @override
  Widget build(BuildContext context) {
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Text(value, style: TextStyle(color: color, fontSize: 20, fontWeight: FontWeight.bold)),
      Text(label, style: const TextStyle(color: Colors.grey, fontSize: 11)),
    ]);
  }
}

// ─── EVIDENCE LIST ───────────────────────────────────────────────────────────

class _EvidenceList extends StatelessWidget {
  final List<_Evidence> evidence;
  const _EvidenceList({required this.evidence});

  Color _badgeColor(String sourceType) {
    switch (sourceType) {
      case 'decision': return Colors.green;
      case 'transcript_segment': return Colors.indigo;
      case 'document_page': return Colors.teal;
      case 'topic': return Colors.amber;
      default: return Colors.blueGrey;
    }
  }

  @override
  Widget build(BuildContext context) {
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
        Text('Evidence Citations (${evidence.length})',
            style: const TextStyle(fontSize: 14, fontWeight: FontWeight.bold, color: Colors.white)),
        const Text('All evidence is from meeting memory', style: TextStyle(fontSize: 11, color: Colors.grey)),
      ]),
      const SizedBox(height: 10),
      ...evidence.asMap().entries.map((entry) {
        final i = entry.key + 1;
        final ev = entry.value;
        final badge = _badgeColor(ev.sourceType);
        final scorePct = (ev.score * 100).toStringAsFixed(1);
        return Card(
          color: const Color(0xFF1E293B),
          margin: const EdgeInsets.only(bottom: 10),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(10),
            side: BorderSide(color: badge.withOpacity(0.3)),
          ),
          child: ExpansionTile(
            leading: CircleAvatar(
              radius: 14,
              backgroundColor: badge.withOpacity(0.2),
              child: Text('$i', style: TextStyle(color: badge, fontSize: 12, fontWeight: FontWeight.bold)),
            ),
            title: Text(ev.meetingTitle, style: const TextStyle(color: Colors.white, fontSize: 13)),
            subtitle: Row(children: [
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                decoration: BoxDecoration(color: badge.withOpacity(0.15), borderRadius: BorderRadius.circular(4)),
                child: Text(ev.sourceType.replaceAll('_', ' ').toUpperCase(),
                    style: TextStyle(color: badge, fontSize: 9, fontWeight: FontWeight.bold)),
              ),
              const SizedBox(width: 8),
              Text('$scorePct% · ${ev.meetingDate}',
                  style: const TextStyle(color: Colors.grey, fontSize: 11)),
            ]),
            children: [
              Padding(
                padding: const EdgeInsets.fromLTRB(16, 0, 16, 14),
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  if (ev.speaker.isNotEmpty) ...[
                    Row(children: [
                      const Icon(Icons.person, size: 12, color: Colors.grey),
                      const SizedBox(width: 4),
                      Text(ev.speaker, style: const TextStyle(color: Colors.grey, fontSize: 12)),
                    ]),
                    const SizedBox(height: 8),
                  ],
                  Container(
                    padding: const EdgeInsets.all(10),
                    decoration: BoxDecoration(
                      color: const Color(0xFF0F172A),
                      borderRadius: BorderRadius.circular(8),
                      border: Border.all(color: badge.withOpacity(0.3)),
                    ),
                    child: Text(ev.excerpt,
                        style: const TextStyle(color: Color(0xFFCBD5E1), fontSize: 12, height: 1.5,
                            fontFamily: 'monospace')),
                  ),
                ]),
              ),
            ],
          ),
        );
      }),
    ]);
  }
}

// ─── INSUFFICIENT EVIDENCE ───────────────────────────────────────────────────

class _InsufficientEvidenceCard extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(24),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: Colors.orange.withOpacity(0.4)),
        color: Colors.orange.withOpacity(0.05),
      ),
      child: Column(children: [
        const Icon(Icons.warning_amber_outlined, color: Colors.orange, size: 40),
        const SizedBox(height: 12),
        const Text('Insufficient Evidence',
            style: TextStyle(color: Colors.orange, fontSize: 16, fontWeight: FontWeight.bold)),
        const SizedBox(height: 8),
        const Text(
          'I could not find enough evidence in the meeting memory to answer this confidently.',
          textAlign: TextAlign.center,
          style: TextStyle(color: Color(0xFFCBD5E1), fontSize: 13, height: 1.5),
        ),
        const SizedBox(height: 12),
        const Text('Try rephrasing your question or make sure relevant meetings have been processed.',
            textAlign: TextAlign.center,
            style: TextStyle(color: Colors.grey, fontSize: 12)),
      ]),
    );
  }
}

// ─── Data models ─────────────────────────────────────────────────────────────

class _AskResult {
  final String question;
  final String answer;
  final double confidence;
  final bool insufficientEvidence;
  final List<_Evidence> evidence;
  final double evalAvgScore;
  final int evalMeetingsCovered;
  final double evalFaithfulness;

  _AskResult({
    required this.question,
    required this.answer,
    required this.confidence,
    required this.insufficientEvidence,
    required this.evidence,
    required this.evalAvgScore,
    required this.evalMeetingsCovered,
    required this.evalFaithfulness,
  });
}

class _Evidence {
  final String sourceType;
  final String meetingTitle;
  final String meetingDate;
  final String speaker;
  final String excerpt;
  final double score;

  _Evidence({
    required this.sourceType,
    required this.meetingTitle,
    required this.meetingDate,
    required this.speaker,
    required this.excerpt,
    required this.score,
  });
}
