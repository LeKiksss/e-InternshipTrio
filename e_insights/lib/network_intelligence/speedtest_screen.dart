import 'package:flutter/material.dart';
import 'package:latlong2/latlong.dart';
import 'speedtest_service.dart';
import 'coverage_map_widget.dart';
import 'ai_insight_service.dart';

class TestSpeedScreen extends StatefulWidget {
  const TestSpeedScreen({super.key});

  @override
  State<TestSpeedScreen> createState() => _TestSpeedScreenState();
}

class _TestSpeedScreenState extends State<TestSpeedScreen> {
  final AiInsightService _aiService = AiInsightService(); 
  final SpeedTestService _testService = SpeedTestService();

  double _speed = 0.0;
  double _progress = 0.0;
  String _phase = 'Ready to test';
  bool _isLoading = false;
  bool _isCompleted = false;

  // AI & Last Result States
  String _aiInsightText = '';
  double _lastDownloadMbps = 0.0;
  String _lastLocation = '';
  String _lastDate = '';
  bool _hasPreviousResult = false;

  // Map tracking states
  LatLng? _currentMapCenter;
  final List<Map<String, dynamic>> _coveragePoints = [];

  void _runTest() {
    setState(() {
      _isLoading = true;
      _isCompleted = false;
      _speed = 0.0;
      _progress = 0.0;
      _phase = 'Starting location & test...';
    });

    _testService.executeLiveSpeedTest(
      onProgressUpdate: (speed, progress, phase) {
        setState(() {
          _speed = speed;
          _progress = progress;
          _phase = phase;
        });
      },
      onComplete: (download, upload, location) async {
        final now = DateTime.now();
        final formattedDate =
            '${now.day} ${_getMonthName(now.month)} ${now.year}, ${now.hour.toString().padLeft(2, '0')}:${now.minute.toString().padLeft(2, '0')}';

        final double? currentLat = _testService.currentLatitude;
        final double? currentLng = _testService.currentLongitude;

        setState(() {
          _isLoading = false;
          _isCompleted = true;
          _hasPreviousResult = true;
          _phase =
              'Done! Location: $location\nDownload: ${download.toStringAsFixed(1)} Mbps | Upload: ${upload.toStringAsFixed(1)} Mbps';
          _lastDownloadMbps = download;
          _lastLocation = location;
          _lastDate = formattedDate;

          if (currentLat != null && currentLng != null) {
            final newCenter = LatLng(currentLat, currentLng);
            _currentMapCenter = newCenter;
            _coveragePoints.add({
              'lat': currentLat,
              'lng': currentLng,
              'downloadMbps': download,
            });
          }
        });

        // Background call to Cloud Function without hardcoded fallback strings
        final insight = await _aiService.generateSpeedInsight(
  downloadMbps: download,
  uploadMbps: upload,
  location: location,
);

if (mounted) {
  setState(() {
    _hasPreviousResult = true;
    _aiInsightText = insight;
  });
}
      },
      onError: (error) {
        setState(() {
          _isLoading = false;
          _phase = 'Error: $error';
        });
      },
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Color(0xFFF5F5F7),
      body: Padding(
        padding: const EdgeInsets.all(15.0),
        child: SingleChildScrollView(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              // Header Row
              Row(
                children: [
                  Container(
                      width: 44,
                      height: 44,
                      decoration: BoxDecoration(
                        color: const Color.fromARGB(255, 249, 213, 213),
                        borderRadius: BorderRadius.circular(16),
                      ),
                      child: const Icon(
                        Icons.signal_cellular_alt_rounded,
                        color: Color.fromARGB(255, 255, 71, 71),
                      )),
                  const SizedBox(width: 20),
                  const Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        Text(
                          "NETWORK INTELLIGENCE",
                          style: TextStyle(
                              fontWeight: FontWeight.bold,
                              color: Colors.grey,
                              fontSize: 12),
                        ),
                        Text(
                          "Check Your Connection",
                          style: TextStyle(
                              fontWeight: FontWeight.bold,
                              color: Colors.black,
                              fontSize: 17),
                        ),
                        Text(
                          "Run a deterministic speed test and understand what the result means.",
                          style: TextStyle(
                              fontWeight: FontWeight.bold,
                              color: Colors.grey,
                              fontSize: 12),
                        ),
                      ],
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 20),

              // 1. LATEST RESULT CONTAINER
              Container(
                width: double.infinity,
                decoration: BoxDecoration(
  color: Colors.white,
  borderRadius: BorderRadius.circular(16),
  boxShadow: [
    BoxShadow(
      color: Colors.black.withOpacity(0.06),
      blurRadius: 12,
      offset: const Offset(0, 4),
    ),
  ],
),
                padding:
                    const EdgeInsets.symmetric(vertical: 20, horizontal: 16),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text(
                      'LATEST RESULT',
                      style: TextStyle(
                        fontSize: 12,
                        fontWeight: FontWeight.bold,
                        color: Colors.grey,
                        letterSpacing: 0.8,
                      ),
                    ),
                    const SizedBox(height: 8),

                    // Main Text + Badge Row
                    Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Expanded(
                          child: Text(
                            _hasPreviousResult
                                ? _aiInsightText
                                : 'Run a speed test to view connection insights.',
                            style: const TextStyle(
                              fontSize: 14,
                              fontWeight: FontWeight.w800,
                              color: Color(0xFF1C1C1E),
                              height: 1.25,
                            ),
                          ),
                        ),
                        if (_hasPreviousResult) ...[
                          const SizedBox(width: 12),
                          Container(
                            padding: const EdgeInsets.symmetric(
                                horizontal: 10, vertical: 6),
                            decoration: BoxDecoration(
                              color: const Color(0xFFEEF4FF),
                              borderRadius: BorderRadius.circular(10),
                            ),
                            child: Column(
                              children: [
                                Text(
                                  '${_lastDownloadMbps.toInt()}',
                                  style: const TextStyle(
                                    fontSize: 14,
                                    fontWeight: FontWeight.w800,
                                    color: Color(0xFF1E61F0),
                                  ),
                                ),
                                const Text(
                                  'Mbps',
                                  style: TextStyle(
                                    fontSize: 10,
                                    fontWeight: FontWeight.w700,
                                    color: Color(0xFF1E61F0),
                                  ),
                                ),
                              ],
                            ),
                          ),
                        ],
                      ],
                    ),

                    if (_hasPreviousResult) ...[
                      const SizedBox(height: 12),
                      Text(
                        '$_lastDate · $_lastLocation',
                        style: const TextStyle(
                          fontSize: 12,
                          color: Colors.grey,
                          fontWeight: FontWeight.w500,
                        ),
                      ),
                    ],
                  ],
                ),
              ),

              const SizedBox(height: 15),

              // 2. SPEED TEST RUNNER CONTAINER
              // 2. SPEED TEST RUNNER CONTAINER
Container(
  width: double.infinity,
  decoration: BoxDecoration(
    color: Colors.white,
    borderRadius: BorderRadius.circular(16),
    boxShadow: [
      BoxShadow(
        color: Colors.black.withOpacity(0.06),
        blurRadius: 12,
        offset: const Offset(0, 4),
      ),
    ],
  ),
  padding: const EdgeInsets.symmetric(vertical: 24, horizontal: 16),
  child: AnimatedSize(
    duration: const Duration(milliseconds: 300),
    curve: Curves.easeInOut,
    child: (_isLoading || _isCompleted)
        ? _buildProgressState()
        : _buildIdleState(),
  ),
),

              // 3. COVERAGE MAP CONTAINER
              if (_currentMapCenter != null) ...[
                const SizedBox(height: 15),
                CoverageMapWidget(
                  currentCenter: _currentMapCenter!,
                  coveragePoints: _coveragePoints,
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }

  String _getMonthName(int month) {
    const months = [
      'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
      'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'
    ];
    return months[month - 1];
  }
  Widget _buildIdleState() {
  return Column(
    key: const ValueKey('idle'),
    mainAxisSize: MainAxisSize.min,
    children: [
      Icon(Icons.speed_rounded, size: 48, color: Colors.grey.shade400),
      const SizedBox(height: 16),
      Text(
        'Ready when you are',
        style: TextStyle(
          fontSize: 15,
          color: Colors.grey.shade700,
          fontWeight: FontWeight.w500,
        ),
      ),
      const SizedBox(height: 20),
      SizedBox(
        width: double.infinity,
        child: ElevatedButton(
          style: ElevatedButton.styleFrom(
            backgroundColor: Colors.red,
            padding: const EdgeInsets.symmetric(vertical: 14),
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(8),
            ),
          ),
          onPressed: _runTest,
          child: const Text(
            'Run Speed Test',
            style: TextStyle(
              color: Colors.white,
              fontWeight: FontWeight.bold,
              fontSize: 16,
            ),
          ),
        ),
      ),
    ],
  );
}

Widget _buildProgressState() {
  return Column(
    key: const ValueKey('progress'),
    mainAxisSize: MainAxisSize.min,
    children: [
      _isCompleted
          ? Container(
              width: 180,
              height: 180,
              decoration: const BoxDecoration(
                color: Color(0xFFE8F5E9),
                shape: BoxShape.circle,
              ),
              child: const Icon(
                Icons.check_circle_rounded,
                color: Colors.green,
                size: 110,
              ),
            )
          : Stack(
              alignment: Alignment.center,
              children: [
                SizedBox(
                  width: 180,
                  height: 180,
                  child: CircularProgressIndicator(
                    value: _isLoading ? _progress : 0.0,
                    strokeWidth: 12,
                    backgroundColor: Colors.grey.shade300,
                    color: Color.fromARGB(255, 244, 2, 2),
                    strokeCap: StrokeCap.round,
                  ),
                ),
                Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Text(
                      _speed.toStringAsFixed(1),
                      style: const TextStyle(
                        fontSize: 36,
                        fontWeight: FontWeight.bold,
                      ),
                    ),
                    const Text(
                      'Mbps',
                      style: TextStyle(
                        fontSize: 14,
                        color: Colors.grey,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                  ],
                ),
              ],
            ),
      const SizedBox(height: 24),
      Text(
        _phase,
        textAlign: TextAlign.center,
        style: TextStyle(
          fontSize: 15,
          color: Colors.grey.shade800,
          height: 1.4,
        ),
      ),
      const SizedBox(height: 24),
      if (_isCompleted)
        SizedBox(
          width: double.infinity,
          child: OutlinedButton(
            style: OutlinedButton.styleFrom(
              padding: const EdgeInsets.symmetric(vertical: 14),
              side: const BorderSide(color: Color.fromARGB(255, 244, 2, 2)),
              shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(8),
              ),
            ),
            onPressed: _runTest,
            child: const Text(
              'Run Again',
              style: TextStyle(
                color: Color.fromARGB(255, 244, 2, 2),
                fontWeight: FontWeight.bold,
                fontSize: 16,
              ),
            ),
          ),
        ),
    ],
  );
}
}