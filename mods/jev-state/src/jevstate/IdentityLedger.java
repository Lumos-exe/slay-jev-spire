package jevstate;

import java.util.IdentityHashMap;
import java.util.UUID;

/** No game dependencies: run persistence and native object identity semantics. */
public final class IdentityLedger {
    private String runId;
    private final IdentityHashMap<Object, String> objects = new IdentityHashMap<Object, String>();

    public IdentityLedger() { reset(null); }
    public void reset(String savedRunId) {
        runId = savedRunId == null ? UUID.randomUUID().toString() : savedRunId;
        objects.clear();
    }
    public String runId() { return runId; }
    public String identify(Object object) {
        if (object == null) return null;
        String id = objects.get(object);
        if (id == null) {
            id = UUID.randomUUID().toString();
            objects.put(object, id);
        }
        return id;
    }
}
