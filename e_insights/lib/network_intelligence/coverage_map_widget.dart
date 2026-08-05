import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:latlong2/latlong.dart';
import 'package:cloud_firestore/cloud_firestore.dart';

class CoverageMapWidget extends StatefulWidget {
  final LatLng currentCenter;
  final List<Map<String, dynamic>> coveragePoints;

  const CoverageMapWidget({
    super.key,
    required this.currentCenter,
    required this.coveragePoints,
  });

  @override
  State<CoverageMapWidget> createState() => _CoverageMapWidgetState();
}

class _CoverageMapWidgetState extends State<CoverageMapWidget> {
  final CommunityCoverageService _communityService = CommunityCoverageService();
  List<Map<String, dynamic>> _communityPoints = [];
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _loadCommunityPoints();
  }

  Future<void> _loadCommunityPoints() async {
    final points = await _communityService.fetchCommunityPoints();
    if (mounted) {
      setState(() {
        _communityPoints = points;
        _loading = false;
      });
    }
  }

  Color _getSpeedColor(double speedMbps) {
    if (speedMbps >= 100) return const Color(0xFF22C55E);
    if (speedMbps >= 30) return const Color(0xFFEAB308);
    return const Color(0xFFEF4444);
  }

  @override
  Widget build(BuildContext context) {
    final allPoints = [...widget.coveragePoints, ..._communityPoints];

    return Container(
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
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              const Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text('COVERAGE MAP',
                      style: TextStyle(fontSize: 12, fontWeight: FontWeight.bold, color: Colors.grey, letterSpacing: 0.8)),
                  SizedBox(height: 2),
                  Text('Network Overview',
                      style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold, color: Colors.black)),
                ],
              ),
              TextButton(
                onPressed: () {},
                child: const Text('Full map', style: TextStyle(color: Colors.red, fontWeight: FontWeight.bold)),
              ),
            ],
          ),
          const SizedBox(height: 12),
          ClipRRect(
            borderRadius: BorderRadius.circular(12),
            child: SizedBox(
              height: 200,
              child: Stack(
                children: [
                  FlutterMap(
                    options: MapOptions(
                      initialCenter: widget.currentCenter,
                      initialZoom: 11.0,
                    ),
                    children: [
                      TileLayer(
                        urlTemplate: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
                        userAgentPackageName: 'com.eand.app',
                      ),
                      MarkerLayer(
                        markers: allPoints.map((point) {
                          final double speed = (point['downloadMbps'] as num).toDouble();
                          final Color dotColor = _getSpeedColor(speed);
                          return Marker(
                            point: LatLng(point['lat'], point['lng']),
                            width: 28,
                            height: 28,
                            child: Container(
                              decoration: BoxDecoration(shape: BoxShape.circle, color: dotColor.withOpacity(0.25)),
                              child: Center(
                                child: Container(
                                  width: 10,
                                  height: 10,
                                  decoration: BoxDecoration(
                                    shape: BoxShape.circle,
                                    color: dotColor,
                                    border: Border.all(color: Colors.white, width: 2),
                                  ),
                                ),
                              ),
                            ),
                          );
                        }).toList(),
                      ),
                    ],
                  ),
                  if (_loading)
                    const Positioned(
                      top: 8,
                      right: 8,
                      child: SizedBox(
                        width: 16,
                        height: 16,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      ),
                    ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 14),
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceEvenly,
            children: [
              _buildLegendDot(const Color(0xFF22C55E), 'Fast (>100M)'),
              _buildLegendDot(const Color(0xFFEAB308), 'Medium (30-100M)'),
              _buildLegendDot(const Color(0xFFEF4444), 'Weak (<30M)'),
            ],
          ),
        ],
      ),
    );
  }

  Widget _buildLegendDot(Color color, String label) {
    return Row(
      children: [
        Container(width: 8, height: 8, decoration: BoxDecoration(color: color, shape: BoxShape.circle)),
        const SizedBox(width: 6),
        Text(label, style: const TextStyle(fontSize: 11, color: Colors.grey, fontWeight: FontWeight.bold)),
      ],
    );
  }
}


class CommunityCoverageService {
  final FirebaseFirestore _db = FirebaseFirestore.instance;

  Future<List<Map<String, dynamic>>> fetchCommunityPoints() async {
    final snapshot = await _db.collection('users').get();
    final points = <Map<String, dynamic>>[];

    for (final doc in snapshot.docs) {
      final data = doc.data();
      final lat = data['latitude'];
      final lng = data['longitude'];
      final lastTest = data['lastSpeedTest'] as Map<String, dynamic>?;
      final download = lastTest?['downloadMbps'];

      if (lat != null && lng != null && download != null) {
        points.add({
          'lat': (lat as num).toDouble(),
          'lng': (lng as num).toDouble(),
          'downloadMbps': (download as num).toDouble(),
          'name': data['name'] ?? 'User',
        });
      }
    }
    return points;
  }
}