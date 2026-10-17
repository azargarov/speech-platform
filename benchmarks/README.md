# M00 observed experiment

Original benchmark scripts and configuration were reported as part of the separately maintained M00 experiment. No local source directory was present at the checked local VoiceHub benchmark location. Remote access was not performed. Original source files have not been inspected or copied; preservation in this repository is NOT ESTABLISHED. Under a user-approved M01 scope decision, source recovery is deferred and does not block M01 closure. This is not a passed preservation test, and benchmark reproduction is not claimed. No private recordings belong in Git. The local sample is kept at `private/audio/russian.m4a`; the entire root `private/` directory is ignored.

OBSERVED (user-reported; not independently reproduced): faster-whisper 1.2.1, CUDA 12.8, Docker Compose, persistent Hugging Face cache, Whisper large-v3-turbo. Russian M4A duration 21.205 s. Two warmups and ten measured runs. Median transcription 0.666 s, p95 0.705 s, median RTF 0.0314. All ten transcriptions identical. Repeated startup loaded cached model in 2.87 s.

INTERPRETATION: the reported warm-cache run suggests STT is feasible on the stated host. These are workload-specific observations, not universal performance guarantees.

NOT ESTABLISHED: concurrency, other languages/audio, accuracy, cold download/startup, full gateway latency, long-form behavior, resource interference, TTS performance, percentile calculation method, exact benchmark source and image digest.

To archive benchmark sources from a directory available on this machine, run:

```sh
scripts/archive-m00.sh /path/to/local/benchmarks /tmp/m00-benchmark-source.tar

# Or set M00_BENCHMARK_SOURCE and pass only the archive path
M00_BENCHMARK_SOURCE=/path/to/local/benchmarks \
  scripts/archive-m00.sh /tmp/m00-benchmark-source.tar
```

The script includes only code and documentation file types and refuses to overwrite an archive. It does not include audio recordings. Inspect the resulting archive for secrets and private paths before choosing files for Git. Remote access, if needed, is a separate operator action: retrieve the files to a locally accessible directory without modifying the source experiment, then use the same command. No remote access is performed by this script.

## Local audio path

Benchmark commands should read the input path from `SPEECH_BENCHMARK_AUDIO`, with `private/audio/russian.m4a` as the local default. Override it without editing a script or storing the path in a tracked config:

```sh
SPEECH_BENCHMARK_AUDIO=/path/to/another/recording.m4a \
  scripts/with-benchmark-audio.sh python3 path/to/benchmark.py

# Use the private sample by default
scripts/with-benchmark-audio.sh python3 path/to/benchmark.py
```

The helper checks that the file exists and passes its path through the environment; it does not copy or print audio contents. Benchmark scripts should use `Path(os.environ["SPEECH_BENCHMARK_AUDIO"])` (or the equivalent in their runtime). The original benchmark scripts were not available in this repository, so their compatibility with this convention is NOT ESTABLISHED.
