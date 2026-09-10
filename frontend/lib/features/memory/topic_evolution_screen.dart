import 'package:flutter/material.dart';
import '../../core/navigation/app_router.dart';
import '../../core/widgets/enterprise_scaffold.dart';

class TopicEvolutionScreen extends StatelessWidget {
  const TopicEvolutionScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return EnterpriseScaffold(
      title: 'Topic Evolution',
      currentRoute: AppRouter.projectMemory,
      child: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Card(
            color: Theme.of(context).colorScheme.secondaryContainer,
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Row(
                children: [
                  Icon(
                    Icons.trending_up,
                    size: 32,
                    color: Theme.of(context).colorScheme.onSecondaryContainer,
                  ),
                  const SizedBox(width: 16),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          'Cross-Meeting Topic Evolution',
                          style: Theme.of(context).textTheme.titleLarge?.copyWith(
                                color: Theme.of(context).colorScheme.onSecondaryContainer,
                                fontWeight: FontWeight.bold,
                              ),
                        ),
                        const SizedBox(height: 4),
                        Text(
                          'Trace how topics originate, evolve across meetings, involve speakers, and lead to decisions & tasks over time.',
                          style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                                color: Theme.of(context).colorScheme.onSecondaryContainer,
                              ),
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 16),

          // Evolution Node Progression Example Card
          Card(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      Text('Topic: Cloud Infrastructure', style: Theme.of(context).textTheme.titleMedium?.copyWith(fontWeight: FontWeight.bold)),
                      Chip(label: const Text('High Importance'), backgroundColor: Colors.amber.shade100),
                    ],
                  ),
                  const Divider(height: 24),
                  _buildEvolutionStep(context, step: 1, meeting: 'Meeting 1 (Sprint Planning)', title: 'Introduction', subtitle: 'Initial discussion on compute options (AWS Lambda proposed).'),
                  _buildEvolutionStep(context, step: 2, meeting: 'Meeting 2 (Architecture Sync)', title: 'Discussion & Concern', subtitle: 'Cold-start latency concerns raised regarding serverless.'),
                  _buildEvolutionStep(context, step: 3, meeting: 'Meeting 3 (Tech Review)', title: 'Alternative Proposal', subtitle: 'Amazon ECS container service proposed as low-latency alternative.'),
                  _buildEvolutionStep(context, step: 4, meeting: 'Meeting 4 (Executive Signoff)', title: 'Linked Decision', subtitle: 'Final Decision: Selected ECS container architecture.'),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildEvolutionStep(
    BuildContext context, {
    required int step,
    required String meeting,
    required String title,
    required String subtitle,
  }) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          CircleAvatar(
            radius: 14,
            backgroundColor: Theme.of(context).colorScheme.primary,
            child: Text('$step', style: const TextStyle(fontSize: 12, color: Colors.white, fontWeight: FontWeight.bold)),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(meeting, style: TextStyle(fontSize: 12, color: Theme.of(context).colorScheme.secondary, fontWeight: FontWeight.w600)),
                Text(title, style: const TextStyle(fontWeight: FontWeight.bold)),
                Text(subtitle, style: Theme.of(context).textTheme.bodySmall),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
