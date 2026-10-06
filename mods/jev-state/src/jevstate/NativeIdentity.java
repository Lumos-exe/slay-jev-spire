package jevstate;

import basemod.BaseMod;
import basemod.abstracts.CustomSavable;
import basemod.interfaces.PreStartGameSubscriber;
import com.evacipated.cardcrawl.modthespire.lib.*;
import com.megacrit.cardcrawl.dungeons.AbstractDungeon;
import com.megacrit.cardcrawl.rewards.RewardItem;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;

/** Run UUID is stored by BaseMod in the game's save, never inferred from seed.
 * Object identities survive controller restarts. Loading a save constructs new
 * room/reward instances: those receive fresh IDs, so old skips cannot hide them.
 */
@SpireInitializer
public final class NativeIdentity implements PreStartGameSubscriber, CustomSavable<String> {
    public static final IdentityLedger ledger = new IdentityLedger();
    public static void initialize() {
        NativeIdentity identity = new NativeIdentity();
        BaseMod.subscribe(identity);
        BaseMod.addSaveField("jevstate:run_id", identity);
    }
    @Override public void receivePreStartGame() { ledger.reset(null); }
    @Override public String onSave() { return ledger.runId(); }
    @Override public void onLoad(String value) {
        if (value != null) UUID.fromString(value); // Corrupt IDs are not silently reused.
        ledger.reset(value);
    }

    @SpirePatch(cls="communicationmod.GameStateConverter", method="getGameState")
    public static class Game {
        @SpirePostfixPatch
        public static HashMap<String, Object> postfix(HashMap<String, Object> __result) {
            HashMap<String, Object> identity = new HashMap<String, Object>();
            identity.put("version", 1);
            identity.put("run_id", ledger.runId());
            identity.put("room_id", ledger.identify(AbstractDungeon.getCurrRoom()));
            identity.put("encounter_id", ledger.identify(AbstractDungeon.getCurrRoom() == null
                ? null : AbstractDungeon.getCurrRoom().monsters));
            __result.put("jev_identity", identity);
            return __result;
        }
    }

    @SpirePatch(cls="communicationmod.GameStateConverter", method="getCombatRewardState")
    public static class Rewards {
        @SpirePostfixPatch
        @SuppressWarnings("unchecked")
        public static HashMap<String, Object> postfix(HashMap<String, Object> __result) {
            Object exported = __result.get("rewards");
            List<RewardItem> nativeRewards = AbstractDungeon.combatRewardScreen.rewards;
            if (!(exported instanceof List) || ((List<?>) exported).size() != nativeRewards.size())
                return __result; // Unknown alignment cannot authorize hiding a reward.
            List<?> entries = (List<?>) exported;
            for (int i = 0; i < nativeRewards.size(); i++) {
                if (entries.get(i) instanceof Map)
                    ((Map<String, Object>) entries.get(i)).put("reward_source_id", ledger.identify(nativeRewards.get(i)));
            }
            return __result;
        }
    }

    @SpirePatch(cls="communicationmod.GameStateConverter", method="getCardRewardState")
    public static class Cards {
        @SpirePostfixPatch
        public static HashMap<String, Object> postfix(HashMap<String, Object> __result) {
            __result.put("reward_source_id", ledger.identify(AbstractDungeon.cardRewardScreen.rItem));
            return __result;
        }
    }
}
