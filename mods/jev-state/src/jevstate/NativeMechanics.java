package jevstate;

import java.lang.reflect.Method;
import java.lang.reflect.Modifier;
import java.util.*;

/** Generic metadata about the actual loaded class, not an item-name registry.
 * Overridden callbacks describe where behavior can run, not what that behavior
 * does. Runtime patches/event buses may add behavior; never infer "no effect".
 */
public final class NativeMechanics {
    private NativeMechanics() { }
    private static final Map<Class<?>, Map<String,Object>> cache = new HashMap<Class<?>, Map<String,Object>>();

    public static synchronized Map<String,Object> describe(Object instance, Class<?> base) {
        Class<?> actual = instance.getClass();
        Map<String,Object> cached = cache.get(actual);
        if (cached != null) return cached;
        ArrayList<String> callbacks = new ArrayList<String>();
        for (Method contract : base.getDeclaredMethods()) {
            if (Modifier.isStatic(contract.getModifiers()) || Modifier.isPrivate(contract.getModifiers()) || contract.isSynthetic()) continue;
            for (Class<?> type=actual;type!=null && type!=base;type=type.getSuperclass()) {
                try {
                    type.getDeclaredMethod(contract.getName(),contract.getParameterTypes());
                    StringBuilder signature=new StringBuilder(contract.getName()).append('(');
                    for (Class<?> argument:contract.getParameterTypes()) signature.append(argument.getSimpleName()).append(',');
                    callbacks.add(signature.append(')').toString());
                    break;
                } catch (NoSuchMethodException inherited) { }
            }
        }
        Collections.sort(callbacks);
        Map<String,Object> result=new HashMap<String,Object>();
        result.put("java_class",actual.getName());
        result.put("overridden_callbacks",callbacks);
        result.put("scope","Raw subclass fields captured per native decision revision; class values and visual/cache fields do not override normalized live card values. Callbacks/fields are not full effect semantics. Complex unexported fields are listed explicitly.");
        cache.put(actual,result);
        return result;
    }
}
