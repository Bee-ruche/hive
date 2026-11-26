# The local bee's tool image (tools/hive/local.sh): a runtime for hive.py and its gate, egress.py, and nothing of
# the tool itself, which the launcher shows read-only from the protocol's clone. Built on the machine by the launcher,
# from the protocol's commit, never pulled: its tag is this file's own blob id.
#
# The base by its fingerprint: the judge's (tools/judge/Dockerfile.base), Ubuntu 24.04, whose git (2.43) takes
# --attr-source and whose Python (3.12) is the tool's. python3, not python3-minimal: the tool imports argparse, json,
# tempfile, zlib, threading and unicodedata.
#
# Two steps, both through apt, which checks each archive's signature (InRelease) and never turns TLS checking off:
# 1. ca-certificates alone, from the base image's own archive (its ubuntu.sources: archive.ubuntu.com and
#    security.ubuntu.com, as the image ships them). This one package is NOT pinned to the snapshot's date: it is the
#    version those archives hold on the day of the build. The base image holds no CA bundle, and the snapshot is
#    served over https alone (http answers 301), so nothing can come from it before this step.
# 2. git and python3 from Ubuntu's snapshot of one date, over https, so that two machines building this file get the
#    same git and Python (the date's index is old by design: Check-Valid-Until is off for it alone).
FROM mirror.gcr.io/library/ubuntu@sha256:24737cef17f4e22b1977df7d9a05e77c4e28b7da5b8911f8d8ccda136bf3573c
RUN apt-get update -q \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y -q --no-install-recommends ca-certificates \
 && rm -f /etc/apt/sources.list.d/ubuntu.sources \
 && for suite in noble noble-updates noble-security; do \
      echo "deb https://snapshot.ubuntu.com/ubuntu/20261115T000000Z $suite main" >> /etc/apt/sources.list; done \
 && apt-get -o Acquire::Check-Valid-Until=false update -q \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y -q --no-install-recommends git python3 \
 && rm -rf /var/lib/apt/lists/* \
 && mkdir -p /work /hive/protocol/tools/hive /hive/state /hive/outbox /hive/handover /hive/home /probed
USER 65534:65534
