import jevstate.NativeFields;

public class NativeFieldsTest {
    static class Parent {
        protected String description = "Heal 28 HP";
        private int count = 3;
    }
    static class Child extends Parent { }
    public static void main(String[] args) throws Exception {
        Object child = new Child();
        assert "Heal 28 HP".equals(NativeFields.read(child, "description"));
        assert Integer.valueOf(3).equals(NativeFields.read(child, "count"));
        boolean missing = false;
        try { NativeFields.read(child, "absent"); }
        catch (NoSuchFieldException expected) { missing = true; }
        assert missing;
        System.out.println("Native inherited field access passed.");
    }
}
