package jevstate;

import com.evacipated.cardcrawl.modthespire.lib.SpirePatch;
import com.evacipated.cardcrawl.modthespire.lib.SpirePostfixPatch;
import com.evacipated.cardcrawl.modthespire.lib.SpirePrefixPatch;
import com.evacipated.cardcrawl.modthespire.lib.SpireReturn;
import com.megacrit.cardcrawl.cards.AbstractCard;
import com.megacrit.cardcrawl.core.AbstractCreature;
import com.megacrit.cardcrawl.powers.AbstractPower;
import com.megacrit.cardcrawl.relics.AbstractRelic;
import com.megacrit.cardcrawl.potions.AbstractPotion;
import com.megacrit.cardcrawl.dungeons.AbstractDungeon;
import com.megacrit.cardcrawl.monsters.AbstractMonster;
import com.megacrit.cardcrawl.rooms.AbstractRoom;
import java.util.ArrayList;
import java.util.HashMap;

@SpirePatch(cls="communicationmod.GameStateConverter", method="convertCardToJson",
            paramtypez={AbstractCard.class})
public class CardValues {
    private static boolean benchmarkNormalized = false;
    private static com.megacrit.cardcrawl.ui.FtueTip lastTutorial;
    private static final ArrayList<String> tutorialAcknowledgements = new ArrayList<String>();

    @SpirePatch(clz=com.megacrit.cardcrawl.ui.FtueTip.class, method="update")
    public static class TutorialAcknowledgement {
        @SpirePrefixPatch
        public static SpireReturn<Void> prefix(com.megacrit.cardcrawl.ui.FtueTip __instance) {
            if (!Boolean.getBoolean("jev.autoTutorials") || __instance.type == null
                    || AbstractDungeon.ftue != __instance || lastTutorial == __instance) return SpireReturn.Continue();
            lastTutorial = __instance;
            // Exact native GotItButton confirmation branch; no global mouse click.
            com.megacrit.cardcrawl.helpers.controller.CInputActionSet.proceed.unpress();
            com.megacrit.cardcrawl.core.CardCrawlGame.sound.play("DECK_OPEN");
            tutorialAcknowledgements.add(__instance.type.toString());
            if (__instance.type == com.megacrit.cardcrawl.ui.FtueTip.TipType.POWER) {
                AbstractDungeon.cardRewardScreen.reopen();
            } else {
                AbstractDungeon.closeCurrentScreen();
            }
            return SpireReturn.Return(null);
        }
    }

    @SpirePatch(cls="communicationmod.GameStateConverter", method="getGameState")
    public static class AutomationState {
        @SpirePostfixPatch
        public static HashMap<String, Object> postfix(HashMap<String, Object> __result) {
            if (__result != null) {
                HashMap<String, Object> automation = new HashMap<String, Object>();
                automation.put("auto_tutorials", Boolean.getBoolean("jev.autoTutorials"));
                automation.put("tutorial_acknowledgements", new ArrayList<String>(tutorialAcknowledgements));
                automation.put("active_tutorial", AbstractDungeon.ftue != null && AbstractDungeon.ftue.type != null
                        ? AbstractDungeon.ftue.type.toString() : null);
                __result.put("automation", automation);
            }
            return __result;
        }
    }
    @SpirePatch(clz=com.megacrit.cardcrawl.neow.NeowEvent.class, method="buttonEffect", paramtypez={int.class})
    public static class BenchmarkNeow {
        @SpirePrefixPatch
        public static SpireReturn<Void> prefix(com.megacrit.cardcrawl.neow.NeowEvent __instance, int buttonPressed) {
            if (!Boolean.getBoolean("jev.benchmark")) return SpireReturn.Continue();
            AbstractDungeon.getCurrRoom().phase = AbstractRoom.RoomPhase.COMPLETE;
            AbstractDungeon.closeCurrentScreen();
            AbstractDungeon.dungeonMapScreen.open(false);
            return SpireReturn.Return(null);
        }
    }
    @SpirePatch(clz=com.megacrit.cardcrawl.characters.AbstractPlayer.class, method="preBattlePrep")
    public static class BenchmarkSetup {
        @SpirePrefixPatch
        public static void prefix(com.megacrit.cardcrawl.characters.AbstractPlayer __instance) {
            if (!Boolean.getBoolean("jev.benchmark") || AbstractDungeon.floorNum != 1) return;
            com.megacrit.cardcrawl.core.Settings.FAST_MODE = true;
            __instance.maxHealth = 80;
            __instance.currentHealth = 80;
            __instance.masterDeck.group.clear();
            for (int i = 0; i < 5; i++) __instance.masterDeck.addToBottom(com.megacrit.cardcrawl.helpers.CardLibrary.getCard("Strike_R").makeCopy());
            for (int i = 0; i < 4; i++) __instance.masterDeck.addToBottom(com.megacrit.cardcrawl.helpers.CardLibrary.getCard("Defend_R").makeCopy());
            __instance.masterDeck.addToBottom(new com.megacrit.cardcrawl.cards.red.Bash());
            __instance.relics.clear();
            __instance.relics.add(new com.megacrit.cardcrawl.relics.BurningBlood());
            __instance.potionSlots = 3;
            __instance.potions.clear();
            for (int i = 0; i < 3; i++) __instance.potions.add(new com.megacrit.cardcrawl.potions.PotionSlot(i));
            benchmarkNormalized = true;
        }
    }
    @SpirePostfixPatch
    public static HashMap<String, Object> postfix(HashMap<String, Object> __result, AbstractCard card) {
        HashMap<String, Object> values = new HashMap<String, Object>();
        boolean inHand = AbstractDungeon.player != null && AbstractDungeon.player.hand.group.contains(card);
        values.put("source", "game_card_fields");
        values.put("scope", inHand ? "current_hand_card_fields" : "base_card_stats");
        values.put("damage", inHand ? card.damage : card.baseDamage);
        values.put("block", inHand ? card.block : card.baseBlock);
        values.put("magic_number", inHand ? card.magicNumber : card.baseMagicNumber);
        values.put("base_damage", card.baseDamage);
        values.put("base_block", card.baseBlock);
        values.put("base_magic_number", card.baseMagicNumber);
        values.put("cost_for_turn", card.costForTurn);
        values.put("damage_modified", card.isDamageModified);
        values.put("block_modified", card.isBlockModified);
        values.put("magic_number_modified", card.isMagicNumberModified);
        __result.put("native_values", values);
        __result.put("raw_description", card.rawDescription);
        __result.put("target_type", card.target.toString());
        __result.put("free_to_play_once", card.freeToPlayOnce);
        __result.put("exhaust_on_use_once", card.exhaustOnUseOnce);
        __result.put("can_upgrade", card.canUpgrade());
        if (card.canUpgrade()) {
            AbstractCard upgraded = card.makeStatEquivalentCopy();
            upgraded.upgrade();
            HashMap<String, Object> preview = new HashMap<String, Object>();
            preview.put("cost", upgraded.costForTurn);
            preview.put("base_damage", upgraded.baseDamage);
            preview.put("base_block", upgraded.baseBlock);
            preview.put("magic_number", upgraded.magicNumber);
            preview.put("upgrades", upgraded.timesUpgraded);
            __result.put("upgrade_preview", preview);
        }
        if (inHand && AbstractDungeon.getCurrRoom() != null
                && AbstractDungeon.getCurrRoom().phase == AbstractRoom.RoomPhase.COMBAT) {
            ArrayList<Integer> validTargets = new ArrayList<Integer>();
            int targetIndex = 0;
            for (AbstractMonster monster : AbstractDungeon.getMonsters().monsters) {
                if (!monster.isDeadOrEscaped() && !monster.halfDead && card.canUse(AbstractDungeon.player, monster))
                    validTargets.add(targetIndex);
                targetIndex++;
            }
            __result.put("valid_target_indices", validTargets);
        }
        if (AbstractDungeon.player != null && AbstractDungeon.getCurrRoom() != null
                && AbstractDungeon.getCurrRoom().phase == AbstractRoom.RoomPhase.COMBAT
                && inHand && card.baseDamage >= 0) {
            ArrayList<Object> previews = new ArrayList<Object>();
            try {
                int index = 0;
                for (AbstractMonster monster : AbstractDungeon.getMonsters().monsters) {
                    if (!monster.isDead && !monster.isDying && !monster.isEscaping && !monster.halfDead) {
                        AbstractCard copy = card.makeStatEquivalentCopy();
                        copy.applyPowers();
                        copy.calculateCardDamage(monster);
                        HashMap<String, Object> preview = new HashMap<String, Object>();
                        preview.put("target_index", index);
                        preview.put("damage_before_block", copy.multiDamage != null && index < copy.multiDamage.length ? copy.multiDamage[index] : copy.damage);
                        preview.put("source", "game_calculateCardDamage");
                        preview.put("scope", "current_state_damage_calculation_not_action_simulation");
                        previews.add(preview);
                    }
                    index++;
                }
                __result.put("target_damage_previews", previews);
            } catch (RuntimeException failure) {
                __result.put("damage_preview_status", "unavailable");
            }
        }
        return __result;
    }

    @SpirePatch(cls="communicationmod.GameStateConverter", method="getGridState")
    public static class GridSelection {
        @SpirePostfixPatch
        public static HashMap<String, Object> postfix(HashMap<String, Object> __result) {
            if (AbstractDungeon.gridSelectScreen.confirmScreenUp) {
                try {
                    java.lang.reflect.Field hovered = com.megacrit.cardcrawl.screens.select.GridCardSelectScreen.class.getDeclaredField("hoveredCard");
                    hovered.setAccessible(true);
                    AbstractCard card = (AbstractCard) hovered.get(AbstractDungeon.gridSelectScreen);
                    if (card != null) __result.put("pending_card_uuid", card.uuid.toString());
                } catch (ReflectiveOperationException unavailable) {
                    __result.put("pending_card_unknown", true);
                }
            }
            return __result;
        }
    }

    @SpirePatch(cls="communicationmod.GameStateConverter", method="getCombatState")
    public static class Counters {
        @SpirePostfixPatch
        public static HashMap<String, Object> postfix(HashMap<String, Object> __result) {
            HashMap<String, Object> counters = new HashMap<String, Object>();
            int attacks = 0, skills = 0;
            for (AbstractCard card : AbstractDungeon.actionManager.cardsPlayedThisTurn) {
                if (card.type == AbstractCard.CardType.ATTACK) attacks++;
                if (card.type == AbstractCard.CardType.SKILL) skills++;
            }
            counters.put("cards_played", AbstractDungeon.actionManager.cardsPlayedThisTurn.size());
            counters.put("attacks_played", attacks);
            counters.put("skills_played", skills);
            counters.put("attacks_this_combat", AbstractDungeon.actionManager.cardsPlayedThisCombat.stream()
                .filter(card -> card.type == AbstractCard.CardType.ATTACK).count());
            __result.put("turn_counters", counters);
            __result.put("benchmark_normalized", benchmarkNormalized && AbstractDungeon.floorNum == 1);
            return __result;
        }
    }

    @SpirePatch(cls="communicationmod.GameStateConverter", method="convertCreaturePowersToJson",
                paramtypez={AbstractCreature.class})
    public static class Powers {
        @SpirePostfixPatch
        @SuppressWarnings("unchecked")
        public static ArrayList<Object> postfix(ArrayList<Object> __result, AbstractCreature creature) {
            for (Object entry : __result) {
                if (!(entry instanceof HashMap)) continue;
                HashMap<String, Object> state = (HashMap<String, Object>) entry;
                for (AbstractPower power : creature.powers) {
                    if (power.ID.equals(state.get("id"))) {
                        state.put("native_description", power.description);
                        state.put("power_type", power.type.toString());
                        if (power instanceof com.megacrit.cardcrawl.powers.CombustPower) {
                            try {
                                java.lang.reflect.Field loss = power.getClass().getDeclaredField("hpLoss");
                                loss.setAccessible(true);
                                state.put("hp_loss", loss.getInt(power));
                            } catch (ReflectiveOperationException unavailable) {
                                state.put("hp_loss_unknown", true);
                            }
                        }
                        break;
                    }
                }
            }
            return __result;
        }
    }

    @SpirePatch(cls="communicationmod.GameStateConverter", method="convertRelicToJson",
                paramtypez={AbstractRelic.class})
    public static class Relics {
        @SpirePostfixPatch
        public static HashMap<String, Object> postfix(HashMap<String, Object> __result, AbstractRelic relic) {
            __result.put("native_description", relic.description);
            return __result;
        }
    }

    @SpirePatch(cls="communicationmod.GameStateConverter", method="convertPotionToJson",
                paramtypez={AbstractPotion.class})
    public static class Potions {
        @SpirePostfixPatch
        public static HashMap<String, Object> postfix(HashMap<String, Object> __result, AbstractPotion potion) {
            __result.put("native_description", potion.description);
            __result.put("potency", potion.getPotency());
            return __result;
        }
    }
}
