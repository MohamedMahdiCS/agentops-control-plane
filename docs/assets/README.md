# Screenshots

Captured from the real console against a local demo database populated by
`scripts/demo/seed_demo.py`, which runs the actual worker, Tool Gateway,
grader and benchmark runner. No values are mocked.

To regenerate:

```bash
AGENTOPS_OPERATOR_TOKEN=<token> node scripts/demo/capture_screenshots.mjs docs/assets/screenshots
ffmpeg -framerate 12 -i docs/assets/screenshots/frames/f%03d.png \
  -vf "scale=640:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=128:stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=4" \
  -loop 0 docs/assets/screenshots/constellation.gif
rm -r docs/assets/screenshots/frames
```
