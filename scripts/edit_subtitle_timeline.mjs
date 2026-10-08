// Structured stdin bridge used by the live Python server.
import { editSubtitleTimeline, inspectSubtitleTimeline } from '../resolve-advanced/server/subtitle-timeline.mjs';
try {
  let input = '';
  for await (const chunk of process.stdin) input += chunk;
  const request = JSON.parse(input);
  process.stdout.write(JSON.stringify(await (request.operation === 'inspect'
    ? inspectSubtitleTimeline(request) : editSubtitleTimeline(request))));
} catch (error) {
  process.stderr.write(error.message);
  process.exitCode = 1;
}
