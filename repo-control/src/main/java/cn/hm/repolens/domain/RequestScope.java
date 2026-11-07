package cn.hm.repolens.domain;

import java.util.Map;
import org.slf4j.MDC;

/** Logging correlation only. Authorization always receives an explicit authenticated owner. */
public final class RequestScope {
    private static final ThreadLocal<String> ID=new ThreadLocal<>();
    private RequestScope(){}
    public static String get(){return ID.get();}
    public static void set(String value){if(value==null)ID.remove();else ID.set(value);}
    public static Runnable decorate(Runnable task){
        String id=get();Map<String,String> logging=MDC.getCopyOfContextMap();
        return ()->{try{set(id);if(logging==null)MDC.clear();else MDC.setContextMap(logging);task.run();}
            finally{ID.remove();MDC.clear();}};
    }
}
