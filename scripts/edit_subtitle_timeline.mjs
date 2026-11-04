// Structured stdin bridge used by the live Python server.
import { editSubtitleTimeline, inspectSubtitleTimeline, editCaptionTimeline, inspectCaptionTimeline }
  from '../resolve-advanced/server/subtitle-timeline.mjs';
const operations = { inspect: inspectSubtitleTimeline, inspect_captions: inspectCaptionTimeline, write_captions: editCaptionTimeline };
try {
  let input = '';
  for await (const chunk of process.stdin) input += chunk;
  const { operation, ...request } = JSON.parse(input);
  process.stdout.write(JSON.stringify(await (operations[operation] || editSubtitleTimeline)(request)));
} catch (error) {
  process.stderr.write(error.message);
  process.exitCode = 1;
}
