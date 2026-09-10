import 'package:flutter/material.dart';
import '../../core/navigation/app_router.dart';
import '../../core/widgets/api_collection_screen.dart';

class CompanyScreen extends StatelessWidget {
  const CompanyScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return ApiCollectionScreen(
      title: 'Company',
      route: AppRouter.companies,
      icon: Icons.apartment,
      endpoint: '/companies',
      emptyMessage: 'No companies are linked to your account.',
      itemTitle: (item) => '${item['name'] ?? 'Company'}',
      itemSubtitle: (item) => '${item['public_id'] ?? ''} ${item['domain'] ?? ''}',
    );
  }
}
