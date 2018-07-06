import sublime
import sublime_plugin
import json
from collections import namedtuple, defaultdict

Segment = namedtuple('Segment', 'line col count hasCount isRegionEntry')

class FileMapping(object):
	def __init__(self, name, segments):
		super(FileMapping, self).__init__()
		self.name = name
		self.segments = sorted(segments, key = lambda x: (x.line, x.col))
		self.segmentsForLine = defaultdict(list) # line -> [segments]
		self.lineCounts = {} # line -> cnt
		self.maxCount = 0
		prev_seg = None
		for seg in self.segments:
			if prev_seg is not None:
				# Compute line range covered by this segment
				start = prev_seg.line
				end = (seg.line+1) if seg.col > 0 else seg.line
				for line in range(start, end):
					# Update mappings
					self.segmentsForLine[line].append(prev_seg)
			prev_seg = seg
		sort_by_entry = lambda x : (x.isRegionEntry, x.count)
		for line, segments in self.segmentsForLine.items():
			# Order segments for each line by putting region entries
			# first, then by count in descending order
			prioritized = sorted(segments, key = sort_by_entry, reverse = True)
			self.lineCounts[line] = prioritized[0].count
			self.maxCount = max(self.maxCount, prioritized[0].count)

	def countedLines(self):
		for line, cnt in self.lineCounts.items():
			yield line, cnt

	def lineCount(self, line):
		return self.lineCounts.get(line, None)


class LoadCoverageCommand(sublime_plugin.TextCommand):

	REGION_KEY = "coverage-not-covered-regions"
	PHANTOM_SET_KEY = "coverage-phantom-set"

	def __init__(self, *args, **kwargs):
		super(LoadCoverageCommand, self).__init__(*args, **kwargs)
		self.phantom_set = sublime.PhantomSet(self.view, self.PHANTOM_SET_KEY)
		self.view.erase_phantoms(self.PHANTOM_SET_KEY)

	def run(self, edit, show):
		view = self.view
		win = view.window()
		if show:
			title = "Clang Coverage JSON path: "
			win.show_input_panel(title, "", self.on_done, None, None)
		else:
			view.set_read_only(False)
			view.erase_regions(self.REGION_KEY)
			view.erase_phantoms(self.PHANTOM_SET_KEY)

	def on_done(self, path):
		variables = self.view.window().extract_variables()
		current_file = variables['file']
		print("[Coverage] Opening {}".format(path))
		with open(path) as fp:
			json_root = json.load(fp)

			# Check if we support this JSON
			if 'type' not in json_root or 'version' not in json_root:
				print("[Coverage] This doesn't look like a clang coverage JSON")
				return
			ver = json_root['version']
			if ver != "2.0.0":
				print("[Coverage] Unsupported coverage export version")
				return

			# Process JSON
			data = json_root['data'][0]
			try:
				# Find matching filename
				match_file = lambda f : f['filename'] == current_file
				file = next(filter(match_file, data['files']))
			except StopIteration:
				print("[Coverage] Couldn't find a matching file")
				return
			segments = map(lambda x : Segment(*x), file['segments'])
			mapping = FileMapping(file['filename'], segments)
			self.show_coverage(mapping)

	def show_coverage(self, mapping):
		print("[Coverage] Showing coverage")
		self.view.set_read_only(True)
		self.draw_uncovered_segments(mapping)
		self.draw_line_counts(mapping)

	def draw_uncovered_segments(self, mapping):
		view = self.view
		def seg_pair_to_region(pair):
			a, b = pair
			start = view.text_point(a.line - 1, a.col - 1)
			end = view.text_point(b.line - 1, b.col - 1)
			return sublime.Region(start, end)
		pairwise = zip(mapping.segments, mapping.segments[1:])
		uncovered = filter(lambda pair: pair[0].count == 0 and pair[0].isRegionEntry, pairwise)
		regions = list(map(seg_pair_to_region, uncovered))
		print(regions)
		view.erase_regions(self.REGION_KEY)
		view.add_regions(self.REGION_KEY, regions, 'invalid', '', 0)

	def draw_line_counts(self, mapping):
		view = self.view
		max_len = max(4, len(str(mapping.maxCount)))
		color_normal = self.view.style_for_scope('comment')['foreground']
		color_uncovered = self.view.style_for_scope('invalid')['background']

		def create_phantom_count(line_idx):
			cnt = mapping.lineCount(line_idx + 1)
			color = color_uncovered if cnt == 0 else color_normal
			str_cnt = str(cnt) if cnt is not None else ''
			pad_len = max_len - len(str_cnt)
			str_cnt = ("&nbsp;" * pad_len) + str_cnt + "&nbsp;"
			point = view.text_point(line_idx, 0)
			line_region = view.line(point)
			style = "color: {}; ".format(color)
			style += "border-right: 1px solid {}; ".format(color_normal)
			style += "margin-right: 10px;"
			content = '<div style="{}">{}</div>'.format(style, str_cnt)
			return sublime.Phantom(line_region, content, sublime.LAYOUT_INLINE)

		tot_lines, _ = view.rowcol(view.size())
		line_indexes = range(0, tot_lines + 1)
		phantoms = list(map(create_phantom_count, line_indexes))
		self.phantom_set.update(phantoms)

