package cn.hm.repolens.messaging;

import io.opentelemetry.api.OpenTelemetry;
import io.opentelemetry.api.trace.*;
import io.opentelemetry.context.*;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.stereotype.Component;

@Component
public class MessageTracing {
    private final OpenTelemetry telemetry;
    public MessageTracing(ObjectProvider<OpenTelemetry> provider){this.telemetry=provider.getIfAvailable(OpenTelemetry::noop);}
    @FunctionalInterface public interface Work{void run()throws Exception;}
    public void consume(String parent,Work work)throws Exception{
        Context context=Context.root();
        if(parent!=null&&parent.matches("00-[a-f0-9]{32}-[a-f0-9]{16}-0[01]")){
            String[] fields=parent.split("-");
            var remote=SpanContext.createFromRemoteParent(fields[1],fields[2],fields[3].equals("01")?TraceFlags.getSampled():TraceFlags.getDefault(),TraceState.getDefault());
            context=context.with(Span.wrap(remote));
        }
        Span span=telemetry.getTracer("repolens-control").spanBuilder("mq.consume").setParent(context).setSpanKind(SpanKind.CONSUMER).startSpan();
        try(Scope ignored=span.makeCurrent()){work.run();}
        catch(Exception error){span.setStatus(StatusCode.ERROR);span.setAttribute("error.type",error.getClass().getSimpleName());throw error;}
        finally{span.end();}
    }
}
