# BeamBench

BeamBench is a local inspection desk for tabletop lighting test photos.
Run `./start.sh` and open [the desk](http://127.0.0.1:19892/). Run `./start.sh stop`
to stop the service while retaining the named volume.

1. Open the labeled synthetic sample or import a PNG or JPEG. An optional
   reference must have the same framing and image dimensions.
2. Use **Set box** and click two opposite corners to choose the table area.
   Use **Set row** or **Set column** to read an exact profile through the box.
   The numeric controls accept original photo coordinates.
3. Use **Pixel probe** or click a result row to check its position and RGB.
   Inspect the grid illumination map, thresholded footprint, radial falloff,
   clipped tones, color cast, or aligned photo comparison.
4. Save a setup to use those positions and thresholds again. Save an inspection
   to keep its original source, sampled rows, and marked PNG. Use the direct
   download links after saving or reopening an inspection.
5. Use **Photo preparation** to process a copy, then attach a prepared output
   as the aligned reference. Preserve the original framing and dimensions.

Photos are immutable, opaque, displayed-orientation RGB. Limits are 14 MiB
per upload, 8–4096 pixels per side, and four million pixels. Display brightness
uses weighted RGB code values and is relative to the photo. The desk measures
neither physical lux nor camera exposure in EV. Radial distance is in original
pixels. The footprint counts every pixel meeting the level and displays up to
16 component outlines. Reference alignment is supplied by the user.
