# Does the Spinn check its broker's certificate?

Running the machine without Spinn's cloud ([PROTOCOL.md §8](PROTOCOL.md#8-feasibility)) depends on
one fact: when the machine connects to AWS IoT, does it verify the server's TLS certificate?

- **If it doesn't**, a DNS override can send it to a broker on your own network, and a local mode
  of this integration becomes possible.
- **If it does**, a DNS redirect can't work, because nobody but Amazon can produce a certificate it
  would trust. The only route left would be changing the machine's firmware.

[`tools/tls_probe.py`](../tools/tls_probe.py) answers that in one sitting. It listens where the
machine expects AWS IoT, presents a throwaway self-signed certificate, and reports whether the
machine refuses it. If the machine accepts it, the probe also logs the MQTT session that follows:
the machine's client id, what it subscribes to and what it publishes. That's what a local broker
would have to serve.

## Before you start

- **A computer on the same network as the machine** with [`uv`](https://docs.astral.sh/uv/)
  installed, or a Kubernetes node (see [below](#running-it-in-kubernetes)).
- **A DNS server the machine uses that you control:** Pi-hole, AdGuard Home, or a router that
  supports local DNS records.
- **About 15 minutes.** While the override is in place the machine can't reach Spinn's cloud, so
  neither Home Assistant nor the app can control it.

The probe never sends the machine a command or a shadow message, only the acknowledgements MQTT
requires (CONNACK, SUBACK, PUBACK, PINGRESP). Its certificate is generated fresh on each run and
deleted when it exits.

## Steps

1. **Find the hostname the machine looks up.** In your DNS server's query log (Pi-hole: *Query
   Log*; AdGuard Home: *Query log*), filter by the machine's IP address. Your router's DHCP list
   has it; the Wi-Fi module may show up as "espressif". You should see
   `a1gzieuy3t1932-ats.iot.us-east-1.amazonaws.com` or `a1gzieuy3t1932.iot.us-east-1.amazonaws.com`.
   - If it uses another name, add `--name <that name>` in step 2.
   - If you see no queries from it at all, it may use its own DNS server (such as 8.8.8.8). Then a
     local override won't reach it.

2. **Start the probe** from your checkout:

   ```bash
   uv run tools/tls_probe.py
   ```

   It prints the address to point the names at (check it's this computer's LAN address). It
   listens on 8883, the MQTT port, and 443, which AWS IoT also accepts. On Linux, port 443 needs
   `sudo`; `--port 8883` alone is usually enough.

3. **Add DNS overrides** pointing the hostname(s) from step 1 at that address. In Pi-hole that's
   *Local DNS → DNS Records*; in AdGuard Home, *Filters → DNS rewrites*.

4. **Power-cycle the machine:** unplug it for 10 seconds. Otherwise it keeps its existing
   connection to AWS. If nothing shows up within a few minutes, its DNS answer may still be
   cached, so power-cycle it again.

5. **Read the result.** A line appears for each connection attempt. Press Ctrl-C for the summary
   and the verdict.

6. **Undo it.** Remove the DNS overrides, power-cycle the machine, and check that Home Assistant
   shows it online again.

## Reading the result

| The probe says | Meaning | Next |
|---|---|---|
| **REFUSED our certificate**, with a reason like `TLSV1_ALERT_UNKNOWN_CA` or *closed after receiving our certificate* | The machine verifies the broker's certificate. | A DNS redirect is out; local control would need firmware changes. |
| **ACCEPTED our untrusted certificate**, followed by MQTT lines | The machine doesn't verify. | Run it again with `--wrong-name` to see whether it checks hostnames, then share the summary so the local broker can be designed. |
| **hung up during the handshake … without saying why** (before naming a server) | Probably verifies, but not conclusive. | Share the log. |
| **couldn't agree on TLS settings** | Says nothing about certificates. | Share the reason; the probe may need adjusting. |
| **No connections** | The override didn't reach the machine. | Recheck step 1, then power-cycle again. |

Some TLS libraries, including AWS's own device SDK, refuse a certificate by quietly closing the
connection. The probe still counts that as a refusal when it happens right after the machine
received the certificate: the probe accepts every cipher and protocol version, so nothing else
could have put the machine off at that point.

The summary includes the machine's MQTT client id, which is its thing name, an identifier for
your machine. Remove it before posting the output anywhere public.

## Running it in Kubernetes

The machine has to reach the probe on your LAN, so run it with `hostNetwork` and point the DNS
overrides at that node's address:

```bash
kubectl create configmap tls-probe --from-file=tools/tls_probe.py
kubectl apply -f - <<'EOF'
apiVersion: v1
kind: Pod
metadata:
  name: tls-probe
spec:
  hostNetwork: true
  restartPolicy: Never
  containers:
    - name: probe
      image: python:3.13-slim
      command: ["sh", "-c", "pip install -q 'cryptography>=42' && python /probe/tls_probe.py --port 8883 --minutes 30"]
      volumeMounts:
        - { name: probe, mountPath: /probe }
  volumes:
    - name: probe
      configMap: { name: tls-probe }
EOF
kubectl logs -f tls-probe      # the address it prints is the node's
```

It prints the summary after 30 minutes, or when you delete the pod:

```bash
kubectl delete pod tls-probe && kubectl delete configmap tls-probe
```

If something on that node already listens on 8883 (a TLS MQTT broker, say), pick another node.
