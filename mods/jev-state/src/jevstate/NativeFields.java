package jevstate;

import java.lang.reflect.Field;
import java.lang.reflect.Array;
import java.lang.reflect.Modifier;
import java.util.*;
import java.util.function.BiFunction;

/** Read explicitly named native data across its actual class hierarchy. */
public final class NativeFields {
    private NativeFields() { }
    private static final Map<Class<?>,Map<Class<?>,List<Field>>> cache = new HashMap<Class<?>,Map<Class<?>,List<Field>>>();
    private static long observationRevision=Long.MIN_VALUE;
    private static final IdentityHashMap<Object,Map<Class<?>,Map<String,Object>>> observations = new IdentityHashMap<Object,Map<Class<?>,Map<String,Object>>>();

    /** Optional extension data shares the native decision boundary. Animation
     * timers must not turn repeated reads of one decision into new observations.
     * Live normalized state and native action validation are never cached here.
     */
    public static synchronized Map<String,Object> atRevision(Object target, Class<?> base, long revision,
            BiFunction<Class<?>,Object,Object> reference) {
        if (observationRevision!=revision) { observations.clear();observationRevision=revision; }
        Map<Class<?>,Map<String,Object>> byBase=observations.get(target);
        if (byBase==null) { byBase=new HashMap<Class<?>,Map<String,Object>>();observations.put(target,byBase); }
        if (!byBase.containsKey(base)) byBase.put(base,snapshot(target,base,reference));
        return byBase.get(base);
    }

    private static synchronized List<Field> fields(Class<?> actual, Class<?> base) {
        Map<Class<?>,List<Field>> byBase=cache.get(actual);
        if (byBase==null) { byBase=new HashMap<Class<?>,List<Field>>();cache.put(actual,byBase); }
        if (!byBase.containsKey(base)) {
            ArrayList<Field> result=new ArrayList<Field>();
            for (Class<?> type=actual;type!=null && type!=base;type=type.getSuperclass()) {
                for (Field field:type.getDeclaredFields()) if (!field.isSynthetic()) result.add(field);
            }
            byBase.put(base,Collections.unmodifiableList(result));
        }
        return byBase.get(base);
    }

    private static boolean scalar(Class<?> type) {
        if (type.isArray()) return scalar(type.getComponentType());
        return type.isPrimitive() || type==String.class || type.isEnum()
            || type==Boolean.class || type==Character.class || type==Byte.class
            || type==Short.class || type==Integer.class || type==Long.class
            || type==Float.class || type==Double.class;
    }

    private static Object value(Object raw) {
        if (raw==null) return null;
        if (raw.getClass().isArray()) {
            ArrayList<Object> values=new ArrayList<Object>();
            for (int i=0;i<Array.getLength(raw);i++) values.add(value(Array.get(raw,i)));
            return values;
        }
        if (raw instanceof Enum<?>) return ((Enum<?>)raw).name();
        if (raw instanceof Character) return raw.toString();
        if ((raw instanceof Double && !Double.isFinite((Double)raw))
            || (raw instanceof Float && !Float.isFinite((Float)raw))) {
            return Collections.singletonMap("non_finite",raw.toString());
        }
        return raw;
    }

    /** Read actual subclass data without invoking gameplay methods or guessing
     * mechanics from IDs. Complex object graphs are explicitly reported rather
     * than traversed. A caller may encode known native references, not effects.
     */
    public static Map<String,Object> snapshot(Object target, Class<?> base,
            BiFunction<Class<?>,Object,Object> reference) {
        TreeMap<String,Object> instance=new TreeMap<String,Object>();
        TreeMap<String,Object> shared=new TreeMap<String,Object>();
        TreeMap<String,Object> references=new TreeMap<String,Object>();
        ArrayList<String> unavailable=new ArrayList<String>(), skipped=new ArrayList<String>();
        HashSet<String> names=new HashSet<String>();
        for (Field field:fields(target.getClass(),base)) {
            String name=field.getName();
            if (!names.add(name)) name=field.getDeclaringClass().getName()+"#"+name;
            try {
                field.setAccessible(true);
                Object raw=field.get(target);
                if (scalar(field.getType())) {
                    (Modifier.isStatic(field.getModifiers()) ? shared : instance).put(name,value(raw));
                } else {
                    Object encoded=reference==null ? null : reference.apply(field.getType(),raw);
                    if (encoded==null) skipped.add(name); else references.put(name,encoded);
                }
            } catch (ReflectiveOperationException | RuntimeException error) {
                unavailable.add(name+":"+error.getClass().getSimpleName());
            }
        }
        Map<String,Object> result=new TreeMap<String,Object>();
        result.put("instance_fields",instance);result.put("class_fields",shared);
        if (!references.isEmpty()) result.put("references",references);
        if (!unavailable.isEmpty()) result.put("unreadable_fields",unavailable);
        if (!skipped.isEmpty()) result.put("unexported_object_fields",skipped);
        return result;
    }
    public static Object read(Object target, String name) throws ReflectiveOperationException {
        if (target == null) throw new NoSuchFieldException(name);
        for (Class<?> type = target.getClass(); type != null; type = type.getSuperclass()) {
            try {
                Field field = type.getDeclaredField(name);
                field.setAccessible(true);
                return field.get(target);
            } catch (NoSuchFieldException absentHere) { }
        }
        throw new NoSuchFieldException(name);
    }
}
