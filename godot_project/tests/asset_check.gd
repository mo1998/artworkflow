extends SceneTree
#
# Headless engine-side verification of exported assets.
#
# The Python validator checks pixels; this checks that the engine can actually consume the
# result: the PNG imports as a Texture2D at the expected size, spritesheet metadata parses,
# and every frame rect lies inside the sheet. An asset that passes Python validation but
# fails here is not engine-ready, and the pipeline says so instead of assuming.
#
# Run (the pipeline does this after --import):
#   godot --headless --path godot_project --script res://tests/asset_check.gd

const ASSET_ROOT := "res://assets"
const MARKER := "ARTWORKFLOW_GODOT "

var problems: Array[String] = []
var checked := 0
var sheets := 0
var frames := 0


func _initialize() -> void:
	_scan(ASSET_ROOT)
	_report()


func _scan(dir_path: String) -> void:
	var dir := DirAccess.open(dir_path)
	if dir == null:
		return
	dir.list_dir_begin()
	var name := dir.get_next()
	while name != "":
		if name.begins_with("."):
			name = dir.get_next()
			continue
		var full := dir_path.path_join(name)
		if dir.current_is_dir():
			_scan(full)
		elif name.get_extension().to_lower() == "png":
			_check_texture(full)
		elif name.get_extension().to_lower() == "json":
			_check_json(full)
		name = dir.get_next()
	dir.list_dir_end()


func _check_texture(res_path: String) -> void:
	checked += 1
	var tex := load(res_path)
	if tex == null:
		problems.append("%s failed to load as a resource" % res_path)
		return
	if not (tex is Texture2D):
		problems.append("%s loaded as %s, expected Texture2D" % [res_path, tex.get_class()])
		return
	var size: Vector2 = (tex as Texture2D).get_size()
	if size.x < 1.0 or size.y < 1.0:
		problems.append("%s reported an empty size" % res_path)


func _check_json(res_path: String) -> void:
	var file := FileAccess.open(res_path, FileAccess.READ)
	if file == null:
		problems.append("%s could not be opened" % res_path)
		return
	var text := file.get_as_text()
	file.close()
	var parsed: Variant = JSON.parse_string(text)
	if parsed == null:
		problems.append("%s is not valid JSON" % res_path)
		return
	if not (parsed is Dictionary):
		return
	var data: Dictionary = parsed
	if not data.has("frames"):
		return
	sheets += 1
	var sheet_name: String = str(data.get("sheet", ""))
	var sheet_path := res_path.get_base_dir().path_join(sheet_name)
	if sheet_name.is_empty() or not ResourceLoader.exists(sheet_path):
		problems.append("%s references missing sheet %s" % [res_path, sheet_name])
		return
	var tex := load(sheet_path) as Texture2D
	if tex == null:
		problems.append("%s sheet %s failed to load" % [res_path, sheet_path])
		return
	var sheet_size: Vector2 = tex.get_size()
	var declared: Array = data.get("sheet_size", [])
	if declared.size() == 2 and (int(declared[0]) != int(sheet_size.x) or int(declared[1]) != int(sheet_size.y)):
		problems.append("%s declares sheet size %s but the texture is %s"
			% [res_path, str(declared), str(sheet_size)])
	for entry in data.get("frames", []):
		frames += 1
		var rect: Rect2 = Rect2(float(entry.get("x", 0)), float(entry.get("y", 0)),
			float(entry.get("w", 0)), float(entry.get("h", 0)))
		if rect.position.x < 0.0 or rect.position.y < 0.0 \
				or rect.end.x > sheet_size.x or rect.end.y > sheet_size.y:
			problems.append("%s frame %s at %s is outside the sheet %s"
				% [res_path, str(entry.get("index", "?")), str(rect), str(sheet_size)])


func _report() -> void:
	var payload := {
		"ok": problems.is_empty(),
		"textures_checked": checked,
		"sheets_checked": sheets,
		"frames_checked": frames,
		"problem_count": problems.size(),
		"problems": problems,
	}
	print(MARKER, JSON.stringify(payload))
	quit(0 if problems.is_empty() else 1)
