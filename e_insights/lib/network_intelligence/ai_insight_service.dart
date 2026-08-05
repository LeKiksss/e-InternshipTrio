import 'package:cloud_firestore/cloud_firestore.dart';
import 'package:firebase_ai/firebase_ai.dart';
import 'package:flutter/foundation.dart';

class AiInsightService {
  final FirebaseFirestore _db = FirebaseFirestore.instance;
  final GenerativeModel _model = FirebaseAI.googleAI().generativeModel(
    model: 'gemini-3.5-flash-lite',
  );

  Future<Map<String, dynamic>?> _calculateRegionalMetrics(
    String location,
    double currentDownload,
  ) async {
    try {
      final snapshot = await _db
          .collection('users')
          .where('location', isEqualTo: location)
          .get();

      if (snapshot.docs.isEmpty) return null;

      double totalDownload = 0;
      int count = 0;
      int slowerUserCount = 0;

      for (final doc in snapshot.docs) {
        final data = doc.data();
        final lastTest = data['lastSpeedTest'] as Map<String, dynamic>?;
        final speed = lastTest?['downloadMbps'];
        if (speed != null) {
          final speedNum = (speed as num).toDouble();
          totalDownload += speedNum;
          count++;
          if (currentDownload > speedNum) slowerUserCount++;
        }
      }

      if (count == 0) return null;

      final avgDownload = (totalDownload / count).round();
      final percentile =
          count > 1 ? ((slowerUserCount / (count - 1)) * 100).round() : 100;
      final diffPercentage =
          (((currentDownload - avgDownload) / avgDownload) * 100).round();

      return {
        'avgDownload': avgDownload,
        'percentile': percentile,
        'diffPercentage': diffPercentage,
        'totalUsersInArea': count,
      };
    } catch (e) {
      return null;
    }
  }

Future<String> generateSpeedInsight({
  required double downloadMbps,
  required double uploadMbps,
  required String location,
}) async {
  final regionalData = await _calculateRegionalMetrics(location, downloadMbps);
  final tier = getSpeedTier(downloadMbps);

  String areaContext = '';
  if (regionalData != null) {
    final diff = regionalData['diffPercentage'] as int;
    final comparisonText = diff >= 0
        ? '$diff% faster than average'
        : '${diff.abs()}% slower than average';
    areaContext = '''
    Area Comparison Data:
    - Area Average Download: ${regionalData['avgDownload']} Mbps
    - Performance vs Area: $comparisonText (Faster than ${regionalData['percentile']}% of local users).
    ''';
  }

  final tierGuidance = switch (tier) {
    SpeedTier.slow => '''
      This speed is SLOW (under 25 Mbps). Be honest, not falsely upbeat.
      Sentence 1: State plainly what this speed supports — light browsing, email, music on one device — and note that video will likely buffer and multiple devices will struggle.
      Sentence 2: Give one concrete, actionable next step (e.g. "Consider upgrading your plan or checking for network congestion at this location.").
      ''',
    SpeedTier.medium => '''
      This speed is MEDIUM (25-100 Mbps). Balanced, not overly enthusiastic.
      Sentence 1: State what this speed comfortably supports — one HD stream, video calls, casual gaming.
      Sentence 2: Note the limitation — it may slow down with multiple people streaming 4K or downloading large files simultaneously — and suggest checking again during peak hours if that's a concern.
      ''',
    SpeedTier.good => '''
      This speed is GOOD (100+ Mbps).
      Sentence 1: Summarize the strong everyday activities this supports (4K streaming across devices, smooth WFH, many connected devices).
      Sentence 2: ${regionalData != null ? 'Compare their speed to the local area average using the provided area data.' : 'Reinforce that their network is performing well.'}
      ''',
  };

  final prompt = '''
  You are an AI assistant inside the e& Insights telecom app.
  Give a factual, useful 2-sentence assessment — do not sugarcoat weak results, and do not overstate marginal ones.

  $tierGuidance

  Speed Data:
  - Download: $downloadMbps Mbps
  - Upload: $uploadMbps Mbps
  $areaContext

  Rules:
  - Keep total response under 40 words.
  - Friendly but honest tone — accuracy over positivity.
  - DO NOT mention bill details or data limits.
  - Do not use common AI words like seamless or flawless.
  ''';

  try {
    final response = await _model.generateContent([Content.text(prompt)]);
    return response.text?.trim() ?? 'Connection insight unavailable.';
  } catch (e) {
    debugPrint('AI Insight Error: $e');
    return 'Failed to generate AI insight.';
  }
}
}
enum SpeedTier { slow, medium, good }

SpeedTier getSpeedTier(double downloadMbps) {
  if (downloadMbps < 25) return SpeedTier.slow;
  if (downloadMbps < 100) return SpeedTier.medium;
  return SpeedTier.good;
}
