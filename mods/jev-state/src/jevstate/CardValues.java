package jevstate;

import com.evacipated.cardcrawl.modthespire.lib.SpirePatch;
import com.evacipated.cardcrawl.modthespire.lib.SpirePostfixPatch;
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
