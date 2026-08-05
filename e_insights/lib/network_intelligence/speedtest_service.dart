import 'package:cloud_firestore/cloud_firestore.dart';
import 'package:flutter_speed_test_plus/flutter_speed_test_plus.dart';
import 'package:geolocator/geolocator.dart';
import 'package:geocoding/geocoding.dart' as geocoding;
import 'package:firebase_auth/firebase_auth.dart';

class SpeedTestService {
  final FlutterInternetSpeedTest _speedTest = FlutterInternetSpeedTest();
  final FirebaseFirestore _database = FirebaseFirestore.instance;

  Position? _lastPosition;

  double? get currentLatitude => _lastPosition?.latitude;
  double? get currentLongitude => _lastPosition?.longitude;

  void executeLiveSpeedTest({
    required Function(double speed, double progress, String phase) onProgressUpdate,
    required Function(double finalDownload, double finalUpload, String location) onComplete,
    required Function(String error) onError,
  }) async {
    try {
      Position position = await _getCurrentPosition();
      _lastPosition = position;
      String locationName = await _getLocationName(position);
      double downloadRate = 0.0;
      double uploadRate = 0.0;

      _speedTest.startTesting(
        onStarted: () {
          onProgressUpdate(0, 0, "Initializing Speed Test");
        },
        onProgress: (percent, result) {
          String phase = result.type == TestType.download
              ? 'Testing Download'
              : 'Testing Upload';
          onProgressUpdate(result.transferRate, percent / 100, phase);
        },
        onDownloadComplete: (result) {
          downloadRate = result.transferRate;
        },
        onUploadComplete: (result) {
          uploadRate = result.transferRate;
        },
        onCompleted: (download, upload) async {
          downloadRate = download.transferRate;
          uploadRate = upload.transferRate;
          await _saveTestToFirestore(
            downloadMbps: downloadRate,
            uploadMbps: uploadRate,
            position: position,
            locationName: locationName,
          );
          onComplete(downloadRate, uploadRate, locationName);
        },
        onError: (errorMessage, speedTestError) {
          onError("Speed test error: $errorMessage");
        },
      );
    } catch (e) {
      onError("Location setup failed: $e");
    }
  }

  Future<Position> _getCurrentPosition() async {
    bool serviceEnabled = await Geolocator.isLocationServiceEnabled();
    if (!serviceEnabled) {
      throw "Location Services are Disabled on Your Device";
    }
    LocationPermission permission = await Geolocator.checkPermission();
    if (permission == LocationPermission.denied) {
      permission = await Geolocator.requestPermission();
      if (permission == LocationPermission.denied) {
        throw 'Location permissions are denied.';
      }
    }
    return await Geolocator.getCurrentPosition(
      locationSettings: const LocationSettings(accuracy: LocationAccuracy.high),
    );
  }

  Future<String> _getLocationName(Position position) async {
    try {
      final geo = geocoding.Geocoding();
      List<geocoding.Placemark> placemarks = await geo.placemarkFromCoordinates(
        position.latitude,
        position.longitude,
      );
      if (placemarks.isNotEmpty) {
        final place = placemarks.first;
        return place.subLocality ??
            place.locality ??
            place.administrativeArea ??
            'Unknown Area';
      }
    } catch (_) {}
    return 'Unknown Location';
  }

  Future<void> _saveTestToFirestore({
    required double downloadMbps,
    required double uploadMbps,
    required Position position,
    required String locationName,
  }) async {
    String currentUserId =
        FirebaseAuth.instance.currentUser?.uid ?? 'guest_user_1';

    await _database.collection('speed_tests').add({
      'userId': currentUserId,
      'locationName': locationName,
      'latitude': position.latitude,
      'longitude': position.longitude,
      'downloadMbps': downloadMbps,
      'uploadMbps': uploadMbps,
      'connectionType': '5G cellular',
      'timestamp': FieldValue.serverTimestamp(),
    });
  }
}