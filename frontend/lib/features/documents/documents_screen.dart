import 'package:flutter/material.dart';
import '../../core/navigation/app_router.dart';
import '../../core/widgets/enterprise_scaffold.dart';

class DocumentsScreen extends StatelessWidget {
  const DocumentsScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return EnterpriseScaffold(
      title: 'Documents',
      currentRoute: AppRouter.documents,
      child: const UiState.empty('Document APIs are not available yet, so no document metrics are shown.'),
    );
  }
}
