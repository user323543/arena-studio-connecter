-- ArenaBridgePlugin.lua  –  Arena AI <-> Roblox Studio Bridge
-- Wird von der Connector-App automatisch installiert:
--   %LOCALAPPDATA%\Roblox\Plugins\ArenaBridgePlugin.lua
--
-- So benutzt du es:
--   1. ArenaStudioConnector.bat starten -> dort stehen Tunnel-URL + Token
--   2. In Studio: Plugins-Tab -> "ArenaBridge" -> hier URL + Token eintragen
--   3. "Verbinden" klicken. Das Plugin merkt sich beides für das nächste Mal.
--
-- Das Plugin spricht nur mit deiner Bridge (standardmäßig 127.0.0.1) –
-- niemals direkt mit dem Internet.

-- Vorbelegung: wird beim Installieren von der App eingesetzt.
-- Du kannst die Felder im Plugin jederzeit überschreiben.
local DEFAULT_URL = "__BRIDGE_URL__"       -- z. B. http://127.0.0.1:8765
local DEFAULT_TOKEN = "__BRIDGE_TOKEN__"   -- gleicher Token wie in der .bat

local HttpService = game:GetService("HttpService")
local SETTING_URL = "ArenaBridgeUrl"
local SETTING_TOKEN = "ArenaBridgeToken"

local function setting(key, fallback)
	local ok, value = pcall(function() return plugin:GetSetting(key) end)
	if ok and typeof(value) == "string" and value ~= "" then return value end
	return fallback
end

local bridgeUrl = setting(SETTING_URL, DEFAULT_URL)
local bridgeToken = setting(SETTING_TOKEN, DEFAULT_TOKEN)

--------------------------------------------------------------------------------
-- UI (Dock-Widget mit Feldern für URL + Token)
--------------------------------------------------------------------------------

local gui = nil
do
	local ok, result = pcall(function()
		local info = DockWidgetPluginGuiInfo.new(Enum.InitialDockState.Right, false, false, 340, 340, 300, 280)
		return plugin:CreateDockWidgetPluginGui("ArenaBridgeDock", info)
	end)
	if ok then gui = result end
end
if gui then
	gui.Title = "ArenaBridge"
	gui.Name = "ArenaBridge"
end

local ui = {}
if gui then
	local root = Instance.new("Frame")
	root.Size = UDim2.new(1, 0, 1, 0)
	root.BackgroundColor3 = Color3.fromRGB(30, 30, 34)
	root.BorderSizePixel = 0
	root.Parent = gui

	local layout = Instance.new("UIListLayout")
	layout.Padding = UDim.new(0, 6)
	layout.SortOrder = Enum.SortOrder.LayoutOrder
	layout.Parent = root

	local padding = Instance.new("UIPadding")
	padding.PaddingTop = UDim.new(0, 10)
	padding.PaddingLeft = UDim.new(0, 10)
	padding.PaddingRight = UDim.new(0, 10)
	padding.Parent = root

	local function label(text, size, color, order)
		local l = Instance.new("TextLabel")
		l.Text = text
		l.Size = UDim2.new(1, 0, 0, size)
		l.BackgroundTransparency = 1
		l.Font = Enum.Font.Gotham
		l.TextSize = 13
		l.TextColor3 = color or Color3.fromRGB(235, 235, 240)
		l.TextXAlignment = Enum.TextXAlignment.Left
		l.TextWrapped = true
		l.LayoutOrder = order
		l.Parent = root
		return l
	end

	local function box(placeholder, text, order)
		local b = Instance.new("TextBox")
		b.Size = UDim2.new(1, 0, 0, 30)
		b.BackgroundColor3 = Color3.fromRGB(45, 45, 52)
		b.BorderSizePixel = 0
		b.Font = Enum.Font.Code
		b.TextSize = 13
		b.TextColor3 = Color3.fromRGB(235, 235, 240)
		b.PlaceholderText = placeholder
		b.Text = text or ""
		b.ClearTextOnFocus = false
		b.TextXAlignment = Enum.TextXAlignment.Left
		b.LayoutOrder = order
		b.Parent = root
		return b
	end

	label("Arena Studio Connector", 16, Color3.fromRGB(120, 220, 160), 1)
	label("1) Bridge-URL  2) Token  3) Verbinden", 13, Color3.fromRGB(170, 170, 180), 2)
	label("Bridge-URL (steht in der .bat als \"Lokale URL\")", 13, nil, 3)
	ui.url = box("http://127.0.0.1:8765", bridgeUrl, 4)
	label("Token (steht in der .bat)", 13, nil, 5)
	ui.token = box("Token aus der .bat", bridgeToken, 6)

	local connect = Instance.new("TextButton")
	connect.Size = UDim2.new(1, 0, 0, 34)
	connect.BackgroundColor3 = Color3.fromRGB(60, 160, 110)
	connect.BorderSizePixel = 0
	connect.Font = Enum.Font.GothamMedium
	connect.TextSize = 14
	connect.TextColor3 = Color3.new(1, 1, 1)
	connect.Text = "Verbinden"
	connect.LayoutOrder = 7
	connect.Parent = root
	ui.connect = connect

	ui.status = Instance.new("TextLabel")
	ui.status.Size = UDim2.new(1, 0, 0, 78)
	ui.status.BackgroundTransparency = 1
	ui.status.Font = Enum.Font.Gotham
	ui.status.TextSize = 12
	ui.status.TextColor3 = Color3.fromRGB(190, 190, 200)
	ui.status.TextXAlignment = Enum.TextXAlignment.Left
	ui.status.TextYAlignment = Enum.TextYAlignment.Top
	ui.status.TextWrapped = true
	ui.status.Text = "Nicht verbunden."
	ui.status.LayoutOrder = 8
	ui.status.Parent = root

	ui.hint = Instance.new("TextLabel")
	ui.hint.Size = UDim2.new(1, 0, 0, 40)
	ui.hint.BackgroundTransparency = 1
	ui.hint.Font = Enum.Font.Gotham
	ui.hint.TextSize = 11
	ui.hint.TextColor3 = Color3.fromRGB(150, 150, 160)
	ui.hint.TextXAlignment = Enum.TextXAlignment.Left
	ui.hint.TextYAlignment = Enum.TextYAlignment.Top
	ui.hint.TextWrapped = true
	ui.hint.Text = "URL + Token werden lokal gespeichert und beim nächsten Öffnen wieder eingesetzt."
	ui.hint.LayoutOrder = 9
	ui.hint.Parent = root
end

-- Fallback ohne Dock-Widget: Werte aus der Installation benutzen
local toolbar = plugin:CreateToolbar("Arena AI")
local button = toolbar:CreateButton("ArenaBridge", "Mit Arena-Bridge verbinden/trennen", "rbxassetid://0")
button.ClickableWhenViewportHidden = true

--------------------------------------------------------------------------------
-- Verbindung
--------------------------------------------------------------------------------

local enabled = false
local loopRunning = false

local function setStatus(text, good)
	if ui.status then
		ui.status.Text = text
		ui.status.TextColor3 = good == true and Color3.fromRGB(120, 220, 160)
			or (good == false and Color3.fromRGB(240, 130, 130)
			or Color3.fromRGB(190, 190, 200))
	end
	print("[ArenaBridge] " .. text)
end

local function currentUrl()
	local value = ui.url and ui.url.Text or bridgeUrl
	value = (value or ""):gsub("%s+$", "")
	if value == "" then value = DEFAULT_URL end
	return value
end

local function currentToken()
	local value = ui.token and ui.token.Text or bridgeToken
	return ((value or ""):gsub("%s+$", ""))
end

local function request(method, path, body)
	return HttpService:RequestAsync({
		Url = currentUrl() .. path,
		Method = method,
		Headers = {
			["Authorization"] = "Bearer " .. currentToken(),
			["Content-Type"] = "application/json",
		},
		Body = body and HttpService:JSONEncode(body) or nil,
	})
end

-- Pfad wie "game.Workspace.Part" oder "Workspace.Part" in ein Instance auflösen
local function resolve(path)
	if typeof(path) ~= "string" or path == "" then return nil end
	local parts = string.split(path, ".")
	local current = game
	local i = 1
	if parts[1] == "game" then i = 2 end
	for idx = i, #parts do
		local name = parts[idx]
		if current == game then
			local ok, svc = pcall(function() return game:GetService(name) end)
			if ok and svc then current = svc
			else local child = current:FindFirstChild(name); if not child then return nil end; current = child end
		else
			local child = current:FindFirstChild(name)
			if not child then return nil end
			current = child
		end
	end
	return current
end

local function pathOf(inst)
	local names = {}
	local cur = inst
	while cur and cur ~= game do
		table.insert(names, 1, cur.Name)
		cur = cur.Parent
	end
	return "game." .. table.concat(names, ".")
end

local function convert(value, currentValue)
	if typeof(value) == "table" and value._type then
		local t = value._type
		if t == "Vector3" then return Vector3.new(value.x or 0, value.y or 0, value.z or 0) end
		if t == "Color3" then return Color3.fromRGB(value.r or 255, value.g or 255, value.b or 255) end
		if t == "UDim2" then return UDim2.new(value.xs or 0, value.xo or 0, value.ys or 0, value.yo or 0) end
		if t == "Enum" and typeof(value.value) == "string" then
			local cur = Enum
			for part in string.gmatch(value.value, "[^%.]+") do cur = cur[part] end
			return cur
		end
	end
	return value
end

local function describe(inst, depth, maxDepth)
	local info = { name = inst.Name, className = inst.ClassName, path = pathOf(inst), children = {} }
	if depth < maxDepth then
		for _, c in ipairs(inst:GetChildren()) do
			table.insert(info.children, describe(c, depth + 1, maxDepth))
		end
	end
	return info
end

local handlers = {}

handlers.place_info = function()
	return { placeId = game.PlaceId, universeId = game.GameId, name = game.Name,
		jobId = game.JobId, isStudio = game:GetService("RunService"):IsStudio() }
end

handlers.list_children = function(args)
	local inst = resolve(args.path); assert(inst, "Pfad nicht gefunden: " .. tostring(args.path))
	local out = {}
	for _, c in ipairs(inst:GetChildren()) do
		table.insert(out, { name = c.Name, className = c.ClassName, path = pathOf(c) })
	end
	return out
end

handlers.get_tree = function(args)
	local inst = resolve(args.path or "game.Workspace"); assert(inst, "Pfad nicht gefunden")
	return describe(inst, 0, tonumber(args.depth) or 2)
end

handlers.get_script = function(args)
	local inst = resolve(args.path); assert(inst, "Pfad nicht gefunden")
	assert(inst:IsA("LuaSourceContainer"), "Kein Script: " .. tostring(args.path))
	return { path = args.path, source = inst.Source }
end

handlers.set_script = function(args)
	local inst = resolve(args.path); assert(inst, "Pfad nicht gefunden")
	assert(inst:IsA("LuaSourceContainer"), "Kein Script: " .. tostring(args.path))
	inst.Source = args.source or ""
	return { path = args.path, ok = true }
end

handlers.create_instance = function(args)
	local parent = resolve(args.parent or "game.Workspace"); assert(parent, "Parent nicht gefunden")
	local inst = Instance.new(args.className)
	inst.Name = args.name or args.className
	if args.properties then
		for k, v in pairs(args.properties) do pcall(function() inst[k] = convert(v, inst[k]) end) end
	end
	inst.Parent = parent
	return { path = pathOf(inst), className = inst.ClassName }
end

handlers.set_property = function(args)
	local inst = resolve(args.path); assert(inst, "Pfad nicht gefunden")
	inst[args.property] = convert(args.value, inst[args.property])
	return { path = args.path, property = args.property }
end

handlers.delete_instance = function(args)
	local inst = resolve(args.path); assert(inst, "Pfad nicht gefunden")
	local p = pathOf(inst); inst:Destroy(); return { deleted = p }
end

handlers.execute_luau = function(args)
	assert(typeof(args.code) == "string", "code fehlt")
	local fn, err = loadstring(args.code)
	assert(fn, "loadstring-Fehler (ggf. 'LoadStringEnabled' aktivieren): " .. tostring(err))
	local results = { fn() }
	local texts = {}
	for _, r in ipairs(results) do table.insert(texts, tostring(r)) end
	return { returned = table.concat(texts, ", ") }
end

local function heartbeat()
	pcall(function()
		request("POST", "/plugin/heartbeat", handlers.place_info())
	end)
end

local function loop()
	heartbeat()
	local lastBeat = os.clock()
	while enabled do
		local ok, res = pcall(request, "GET", "/plugin/poll")
		if ok and res and res.Success then
			if ui.status then
				setStatus("Verbunden ✓  PlaceId " .. tostring(game.PlaceId), true)
			end
			local decoded = HttpService:JSONDecode(res.Body)
			local cmd = decoded and decoded.command
			if cmd then
				local okCmd, result = pcall(function()
					local h = handlers[cmd.type]; assert(h, "Unbekanntes Kommando: " .. tostring(cmd.type))
					return h(cmd.args or {})
				end)
				pcall(request, "POST", "/plugin/result", {
					id = cmd.id, ok = okCmd,
					result = okCmd and result or nil,
					error = okCmd and nil or tostring(result),
				})
			end
		elseif ok and res and res.StatusCode == 401 then
			setStatus("Token falsch (HTTP 401). Bitte Token aus der .bat neu eintragen.", false)
			enabled = false
		else
			setStatus("Keine Verbindung zu " .. currentUrl() .. "\nLäuft die .bat noch?", false)
			enabled = false
		end
		if os.clock() - lastBeat > 5 then heartbeat(); lastBeat = os.clock() end
		task.wait(0.8)
	end
	if ui.status then setStatus("Nicht verbunden.", nil) end
	loopRunning = false
	button:SetActive(false)
	if ui.connect then ui.connect.Text = "Verbinden" end
end

local function startConnection()
	local url = currentUrl()
	local token = currentToken()
	if url == "" or not url:match("^https?://") then
		setStatus("Bitte eine Bridge-URL angeben, z. B. http://127.0.0.1:8765", false)
		return
	end
	if token == "" then
		setStatus("Bitte den Token aus der .bat eintragen.", false)
		return
	end
	bridgeUrl = url
	bridgeToken = token
	pcall(function()
		plugin:SetSetting(SETTING_URL, url)
		plugin:SetSetting(SETTING_TOKEN, token)
	end)
	enabled = true
	button:SetActive(true)
	if ui.connect then ui.connect.Text = "Trennen" end
	setStatus("Verbinde mit " .. url .. " …", nil)
	if not loopRunning then
		loopRunning = true
		task.spawn(loop)
	end
end

local function stopConnection()
	enabled = false
	if ui.connect then ui.connect.Text = "Verbinden" end
	button:SetActive(false)
end

if ui.connect then
	ui.connect.MouseButton1Click:Connect(function()
		if enabled then stopConnection() else startConnection() end
	end)
end

button.Click:Connect(function()
	if enabled then stopConnection() else startConnection() end
end)

-- Beim ersten Start direkt verbinden, wenn URL + Token schon gesetzt sind
-- (dann muss man in Studio gar nichts mehr eintippen).
if bridgeToken ~= "" and bridgeToken ~= "__BRIDGE_TOKEN__"
	and bridgeUrl ~= "" and bridgeUrl ~= "__BRIDGE_URL__" then
	task.defer(startConnection)
end

print("[ArenaBridge] Geladen. Plugins-Tab -> ArenaBridge: URL + Token aus der .bat eintragen, dann 'Verbinden'.")
