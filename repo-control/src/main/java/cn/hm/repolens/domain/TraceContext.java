package cn.hm.repolens.domain;

import io.opentelemetry.api.trace.Span;

public final class TraceContext {
    private TraceContext(){}
    public static String parent(){
        var context=Span.current().getSpanContext();
        return context.isValid()?"00-"+context.getTraceId()+"-"+context.getSpanId()+"-"+context.getTraceFlags().asHex():null;
    }
    public static void inject(java.net.http.HttpRequest.Builder request){String parent=parent();if(parent!=null)request.header("traceparent",parent);}
}
