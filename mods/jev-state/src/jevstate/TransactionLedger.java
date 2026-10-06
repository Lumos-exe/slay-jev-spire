package jevstate;

import java.util.LinkedHashMap;
import java.util.Map;
import java.util.UUID;

/** Native, single-flight, revision-guarded action ledger. No game effect inference. */
public final class TransactionLedger {
    public final String epoch = UUID.randomUUID().toString();
    private long revision = 0;
    private final LinkedHashMap<String, Map<String, Object>> receipts = new LinkedHashMap<>();
    private Map<String, Object> active;
    private Map<String, Object> visible;
    private boolean registered;

    private Map<String, Object> receipt(String id, long expected, String command, String status) {
        Map<String, Object> value = new LinkedHashMap<>();
        value.put("id", id); value.put("command", command); value.put("status", status);
        value.put("expected_revision", expected);
        return value;
    }

    private void reject(String id, long expected, String command, String reason, boolean remember) {
        visible = receipt(id, expected, command, "rejected");
        visible.put("error", reason);
        if (remember) { receipts.put(id, visible); trim(); }
    }

    private void trim() {
        while (receipts.size() > 256) {
            for (String key : receipts.keySet()) {
                if (receipts.get(key) != active) { receipts.remove(key); break; }
            }
        }
    }

    public synchronized boolean begin(String requestedEpoch, String id, long expected, String command) {
        if (!epoch.equals(requestedEpoch)) {
            reject(id, expected, command, "epoch_changed", false); return false;
        }
        Map<String, Object> prior = receipts.get(id);
        if (prior != null) {
            if (!command.equals(prior.get("command")) || !Long.valueOf(expected).equals(prior.get("expected_revision")))
                reject(id, expected, command, "id_conflict", false);
            else visible = prior;
            return false;
        }
        if (active != null) { reject(id, expected, command, "busy", true); return false; }
        if (expected != revision) { reject(id, expected, command, "stale_revision", true); return false; }
        active = receipt(id, expected, command, "received");
        visible = active; receipts.put(id, active); registered = false;
        trim();
        return true;
    }

    public synchronized void accepted() {
        if (active != null) active.put("status", "accepted");
    }

    public synchronized void rejected(String reason) {
        if (active != null) {
            active.put("status", "rejected"); active.put("error", reason);
            visible = active; active = null; registered = false;
        }
    }

    public synchronized void commandRegistered() {
        if (active != null && "accepted".equals(active.get("status"))) registered = true;
    }


    public synchronized void decisionBoundary() {
        revision++;
        if (active != null && registered) {
            active.put("status", "settled"); active.put("settled_revision", revision);
            visible = active; active = null; registered = false;
        }
    }

    public synchronized void query(String id) { visible = receipts.get(id); }

    public synchronized long currentRevision() { return revision; }

    public synchronized Map<String, Object> snapshot() {
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("version", 1); result.put("epoch", epoch); result.put("revision", revision);
        result.put("receipt", visible == null ? null : new LinkedHashMap<>(visible));
        return result;
    }
}
