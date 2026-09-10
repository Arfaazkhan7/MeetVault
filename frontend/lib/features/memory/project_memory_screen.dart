import 'package:flutter/material.dart';
import '../../core/navigation/app_router.dart';
import '../../core/widgets/enterprise_scaffold.dart';

class ProjectMemoryScreen extends StatelessWidget {
  const ProjectMemoryScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return EnterpriseScaffold(
      title: 'Project Memory',
      currentRoute: AppRouter.projectMemory,
      child: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          // Banner making it clear Project Memory is compiled from multiple meetings
          Card(
            color: Theme.of(context).colorScheme.primaryContainer,
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Row(
                children: [
                  Icon(
                    Icons.account_tree,
                    size: 32,
                    color: Theme.of(context).colorScheme.onPrimaryContainer,
                  ),
                  const SizedBox(width: 16),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          'Project Memory Dashboard',
                          style: Theme.of(context).textTheme.titleLarge?.copyWith(
                                color: Theme.of(context).colorScheme.onPrimaryContainer,
                                fontWeight: FontWeight.bold,
                              ),
                        ),
                        const SizedBox(height: 4),
                        Text(
                          'Aggregated knowledge from all meetings within the project: discussions, decisions, tasks, recurring topics, documents, and timeline.',
                          style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                                color: Theme.of(context).colorScheme.onPrimaryContainer,
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

          // Dashboard Sections Overview
          _buildDashboardSection(
            context,
            title: 'Recent Discussions & Summaries',
            icon: Icons.forum_outlined,
            description: 'Key takeaways and summaries compiled from across project meetings.',
          ),
          const SizedBox(height: 12),

          _buildDashboardSection(
            context,
            title: 'Important Decisions',
            icon: Icons.gavel_outlined,
            description: 'Agreements, proposals, and decisions agreed upon in project meetings.',
          ),
          const SizedBox(height: 12),

          _buildDashboardSection(
            context,
            title: 'Open Tasks & Deadlines',
            icon: Icons.task_alt_outlined,
            description: 'Pending action items, assigned tasks, and upcoming project deadlines.',
          ),
          const SizedBox(height: 12),

          _buildDashboardSection(
            context,
            title: 'Recurring Topics',
            icon: Icons.repeat_outlined,
            description: 'Themes and topics repeatedly discussed across multiple project meetings.',
          ),
          const SizedBox(height: 12),

          _buildDashboardSection(
            context,
            title: 'Meeting Timeline',
            icon: Icons.timeline_outlined,
            description: 'Chronological sequence of meetings, decision milestones, and document additions.',
          ),
          const SizedBox(height: 12),

          _buildDashboardSection(
            context,
            title: 'Related Documents',
            icon: Icons.description_outlined,
            description: 'PDFs, PPTs, and PPTXs associated with the project or its meetings.',
          ),
        ],
      ),
    );
  }

  Widget _buildDashboardSection(
    BuildContext context, {
    required String title,
    required IconData icon,
    required String description,
  }) {
    return Card(
      child: ListTile(
        leading: CircleAvatar(
          child: Icon(icon),
        ),
        title: Text(title, style: const TextStyle(fontWeight: FontWeight.bold)),
        subtitle: Text(description),
        trailing: const Icon(Icons.arrow_forward_ios, size: 16),
      ),
    );
  }
}
