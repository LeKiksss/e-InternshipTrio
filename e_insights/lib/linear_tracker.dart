import 'package:flutter/material.dart';

class LinearTracker extends StatelessWidget {
  final int current;
  final int total;
  final String label;
  final String type;
  final String Function(int current, int total)? valueFormatter;
  final String Function(int remaining)? remainingFormatter;
  final Color? progressColor;
  final Color? backgroundColor;
  final double warningThreshold;
  final Color? warningColor;

  const LinearTracker({
    super.key,
    required this.current,
    required this.total,
    required this.label,
    required this.type,
    this.valueFormatter,
    this.remainingFormatter,
    this.progressColor,
    this.backgroundColor,
    this.warningThreshold = 0.9, // effectively off unless set
    this.warningColor,
  });

int get remaining {
  final safeTotal = total < 0 ? 0: total;
  return (safeTotal - current).clamp(0, safeTotal);
}
  double get progress => total == 0 ? 0 : (current / total).clamp(0.0, 1.0);

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final isWarning = progress >= warningThreshold;

    final barColor = progressColor ??
        (isWarning
            ? (warningColor ?? Colors.redAccent)
            : Colors.green[600]!);

    final valueText = valueFormatter?.call(current, total) ??
        '$current $type / $total $type';

    final remainingText = remainingFormatter?.call(remaining) ??
        '$remaining $type remaining';

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            Text(
              label,
              style: theme.textTheme.titleMedium?.copyWith(
                fontWeight: FontWeight.w600,
              ),
            ),
            Text(
              valueText,
              style: theme.textTheme.bodyMedium?.copyWith(
                color: theme.colorScheme.onSurfaceVariant,
              ),
            ),
          ],
        ),
        const SizedBox(height: 8),
        ClipRRect(
          borderRadius: BorderRadius.circular(8),
          child: LinearProgressIndicator(
            value: progress,
            minHeight: 10,
            backgroundColor: backgroundColor ??
                theme.colorScheme.surfaceContainerHighest,
            valueColor: AlwaysStoppedAnimation<Color>(barColor),
          ),
        ),
        const SizedBox(height: 6),
        Text(
          remainingText,
          style: theme.textTheme.bodySmall?.copyWith(
            color: theme.colorScheme.onSurfaceVariant,
          ),
        ),
      ],
    );
  }
}