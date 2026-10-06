package jevstate;

import com.evacipated.cardcrawl.modthespire.lib.*;
import com.autoplay.gson.Gson;
import java.util.HashMap;
import java.lang.reflect.InvocationTargetException;

/** Correlates native command acceptance with the next native decision boundary. */
public final class ActionProtocol {
    public static final TransactionLedger ledger = new TransactionLedger();

    private static void publish() {
        try { Class.forName("communicationmod.CommunicationMod").getField("mustSendGameState").setBoolean(null, true); }
        catch (ReflectiveOperationException failure) { throw new IllegalStateException(failure); }
    }

    @SpirePatch(cls="communicationmod.CommandExecutor", method="executeCommand", paramtypez={String.class})
    public static class Execute {
        @SpirePrefixPatch
        public static SpireReturn<Boolean> prefix(String command) {
            if (command.startsWith("JEV_STATUS ")) {
                String[] parts = command.trim().split("\\s+");
                if (parts.length == 3) ledger.query(parts[2]);
                publish(); return SpireReturn.Return(false);
            }
            if (!command.startsWith("JEV_ACTION ")) return SpireReturn.Continue();
            String[] parts = command.trim().split("\\s+", 5);
            if (parts.length != 5 || !parts[2].matches("[A-Za-z0-9._:-]{1,128}")) {
                publish(); return SpireReturn.Return(false);
            }
            long expected;
            try { expected = Long.parseLong(parts[3]); }
            catch (NumberFormatException invalid) { publish(); return SpireReturn.Return(false); }
            String inner = parts[4].trim().replaceAll("\\s+", " ").toUpperCase(java.util.Locale.ROOT);
            if (!ledger.begin(parts[1], parts[2], expected, inner)) {
                publish(); return SpireReturn.Return(false);
            }
            if (!inner.matches("(PLAY|END|CHOOSE|POTION|CONFIRM|PROCEED|SKIP|CANCEL|RETURN|LEAVE|START)( .*)?")) {
                ledger.rejected("unsupported_action"); publish(); return SpireReturn.Return(false);
            }
            try {
                // Re-enter the unwrapped command: normal parser, legality and
                // execution remain owned by CommunicationMod.
                Object result = Class.forName("communicationmod.CommandExecutor")
                    .getMethod("executeCommand", String.class).invoke(null, inner);
                if (!Boolean.TRUE.equals(result)) {
                    ledger.rejected("not_an_action"); publish(); return SpireReturn.Return(false);
                }
                ledger.accepted(); publish();
                return SpireReturn.Return(true);
            } catch (InvocationTargetException invalid) {
                ledger.rejected("native_command_rejected"); publish(); return SpireReturn.Return(false);
            } catch (ReflectiveOperationException unavailable) {
                ledger.rejected("executor_unavailable"); publish(); return SpireReturn.Return(false);
            }
        }
    }

    @SpirePatch(cls="communicationmod.GameStateListener", method="registerCommandExecution")
    public static class Registered {
        @SpirePostfixPatch
        public static void postfix() { ledger.commandRegistered(); }
    }

    @SpirePatch(cls="communicationmod.GameStateListener", method="checkForDungeonStateChange")
    public static class DungeonBoundary {
        @SpirePostfixPatch
        public static boolean postfix(boolean __result) {
            if (__result) ledger.decisionBoundary();
            return __result;
        }
    }

    @SpirePatch(cls="communicationmod.GameStateListener", method="checkForMenuStateChange")
    public static class MenuBoundary {
        @SpirePostfixPatch
        public static boolean postfix(boolean __result) {
            if (__result) ledger.decisionBoundary();
            return __result;
        }
    }

    @SpirePatch(cls="communicationmod.GameStateConverter", method="getCommunicationState")
    public static class State {
        @SpirePostfixPatch
        public static String postfix(String __result) {
            if (!__result.endsWith("}")) return __result;
            return __result.substring(0, __result.length()-1) + ",\"jev_protocol\":"
                + new Gson().toJson(ledger.snapshot()) + "}";
        }
    }
}
