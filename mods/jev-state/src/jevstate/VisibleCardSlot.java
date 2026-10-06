package jevstate;

import java.util.*;
import java.util.function.Supplier;

/** Shared card-board observation: never evaluate hidden card identities. */
public final class VisibleCardSlot {
    public static Map<String,Object> describe(int slot,String reference,boolean revealed,boolean faceUp,
            Supplier<Map<String,Object>> face) {
        Map<String,Object> result=new LinkedHashMap<String,Object>();
        result.put("slot",slot);result.put("card_uuid",reference);
        result.put("known",revealed || faceUp);result.put("face_up",faceUp);
        if (revealed || faceUp) result.put("card",face.get());
        return result;
    }
}
