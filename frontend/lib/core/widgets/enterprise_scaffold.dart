import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../navigation/app_router.dart';
import '../providers/auth_provider.dart';

class NavItem {
  final String label;
  final IconData icon;
  final String route;

  const NavItem(this.label, this.icon, this.route);
}

const _personalNavItems = [
  NavItem('Home', Icons.home_rounded, AppRouter.dashboard),
  NavItem('Meet', Icons.videocam_outlined, AppRouter.meetings),
  NavItem('History', Icons.history, AppRouter.projectMemory),
  NavItem('Meeting Notes', Icons.description_outlined, AppRouter.documents),
  NavItem('Settings', Icons.settings_outlined, AppRouter.settings),
];

const _orgNavItems = [
  NavItem('Home', Icons.home_rounded, AppRouter.dashboard),
  NavItem('Meet', Icons.videocam_outlined, AppRouter.meetings),
  NavItem('History', Icons.history, AppRouter.projectMemory),
  NavItem('Meeting Notes', Icons.description_outlined, AppRouter.documents),
  NavItem('Projects', Icons.folder_outlined, AppRouter.projects),
  NavItem('Team', Icons.people_outline, AppRouter.users),
  NavItem('Settings', Icons.settings_outlined, AppRouter.settings),
];

class EnterpriseScaffold extends StatelessWidget {
  final String title;
  final String currentRoute;
  final Widget child;
  final List<Widget> actions;
  final Widget? floatingActionButton;

  const EnterpriseScaffold({
    super.key,
    required this.title,
    required this.currentRoute,
    required this.child,
    this.actions = const [],
    this.floatingActionButton,
  });

  @override
  Widget build(BuildContext context) {
    final wide = MediaQuery.sizeOf(context).width >= 960;
    final content = Scaffold(
      backgroundColor: const Color(0xFFF7F8FA),
      appBar: wide ? null : AppBar(title: Text(title), actions: actions),
      drawer: wide ? null : Drawer(child: _NavigationList(currentRoute: currentRoute)),
      body: child,
      floatingActionButton: floatingActionButton,
    );

    if (!wide) return content;

    return Scaffold(
      backgroundColor: const Color(0xFFF7F8FA),
      body: Row(
        children: [
          Container(
            width: 232,
            color: const Color(0xFFFBFBFC),
            child: _NavigationList(currentRoute: currentRoute),
          ),
          const VerticalDivider(width: 1, color: Color(0xFFE2E8F0)),
          Expanded(child: content),
        ],
      ),
    );
  }
}

class _NavigationList extends StatelessWidget {
  final String currentRoute;

  const _NavigationList({required this.currentRoute});

  @override
  Widget build(BuildContext context) {
    final authProvider = Provider.of<AuthProvider>(context, listen: false);
    final navItems = authProvider.isOrganization ? _orgNavItems : _personalNavItems;

    return SafeArea(
      child: Column(
        children: [
          // Brand Header
          Padding(
            padding: const EdgeInsets.fromLTRB(20, 20, 20, 24),
            child: Row(
              children: [
                Container(
                  width: 38,
                  height: 38,
                  decoration: BoxDecoration(
                    color: const Color(0xFF5E6AD2),
                    borderRadius: BorderRadius.circular(7),
                  ),
                  child: const Center(
                    child: Text('M', style: TextStyle(color: Colors.white, fontWeight: FontWeight.w900, fontSize: 22)),
                  ),
                ),
                const SizedBox(width: 12),
                const Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text('MeetVault', style: TextStyle(fontSize: 18, fontWeight: FontWeight.w800, color: Color(0xFF171A2B), letterSpacing: -0.2)),
                    Text('Meeting intelligence', style: TextStyle(fontSize: 11, color: Color(0xFF73778C), fontWeight: FontWeight.w500)),
                  ],
                ),
              ],
            ),
          ),

          // Nav Links
          Expanded(
            child: ListView(
              padding: const EdgeInsets.symmetric(horizontal: 14),
              children: [
                for (final item in navItems) _buildNavItem(context, item),
              ],
            ),
          ),

          // Bottom Promo Box
          Padding(
            padding: const EdgeInsets.all(16),
            child: Container(
              padding: const EdgeInsets.all(16),
              decoration: BoxDecoration(
                gradient: const LinearGradient(
                  colors: [Color(0xFF1E293B), Color(0xFF0F172A)],
                  begin: Alignment.topLeft,
                  end: Alignment.bottomRight,
                ),
                borderRadius: BorderRadius.circular(16),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      const Expanded(
                        child: Text(
                          'Turn\nConversations\ninto Knowledge.',
                          style: TextStyle(color: Colors.white, fontWeight: FontWeight.bold, fontSize: 13, height: 1.3),
                        ),
                      ),
                      CircleAvatar(
                        radius: 16,
                        backgroundColor: Colors.white,
                        child: IconButton(
                          padding: EdgeInsets.zero,
                          icon: const Icon(Icons.arrow_forward_rounded, size: 16, color: Color(0xFF0F172A)),
                          onPressed: () => Navigator.pushNamed(context, AppRouter.askMemory),
                        ),
                      ),
                    ],
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildNavItem(BuildContext context, NavItem item) {
    final isSelected = item.route == currentRoute;
    return Container(
      margin: const EdgeInsets.only(bottom: 6),
      child: Material(
        color: isSelected ? const Color(0xFFE9EAFE) : Colors.transparent,
        borderRadius: BorderRadius.circular(6),
        child: InkWell(
        borderRadius: BorderRadius.circular(6),
          onTap: () {
            if (ModalRoute.of(context)?.settings.name != item.route) {
              Navigator.pushReplacementNamed(context, item.route);
            }
          },
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
            child: Row(
              children: [
                Icon(
                  item.icon,
                  size: 20,
                  color: isSelected ? const Color(0xFF5E6AD2) : const Color(0xFF73778C),
                ),
                const SizedBox(width: 14),
                Text(
                  item.label,
                  style: TextStyle(
                    fontSize: 14,
                    fontWeight: isSelected ? FontWeight.w700 : FontWeight.w500,
                    color: isSelected ? const Color(0xFF4C56B8) : const Color(0xFF45495C),
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class UiState extends StatelessWidget {
  final String message;
  final IconData icon;
  final VoidCallback? onRetry;

  const UiState.empty(this.message, {super.key})
      : icon = Icons.inbox_outlined,
        onRetry = null;

  const UiState.error(this.message, {super.key, this.onRetry})
      : icon = Icons.error_outline;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(icon, size: 44, color: Theme.of(context).colorScheme.outline),
            const SizedBox(height: 12),
            Text(message, textAlign: TextAlign.center),
            if (onRetry != null) ...[
              const SizedBox(height: 16),
              FilledButton.icon(
                onPressed: onRetry,
                icon: const Icon(Icons.refresh),
                label: const Text('Retry'),
              ),
            ],
          ],
        ),
      ),
    );
  }
}
