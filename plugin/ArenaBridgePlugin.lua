-- ArenaBridgePlugin.lua  -  Arena AI <-> Roblox Studio Bridge
-- Version 1.3  -  das Fenster geht beim Laden von selbst auf
--
-- Wird von der Connector-App automatisch installiert:
--   %LOCALAPPDATA%\Roblox\Plugins\ArenaBridgePlugin.lua
--
-- Benutzung:
--   1. ArenaStudioConnector.bat starten -> dort stehen Tunnel-URL + Token
--   2. Studio: Plugins-Tab -> ArenaBridge -> "Fenster"
--      (das Fenster ist beim Laden schon offen)
--   3. Bridge-URL + Token eintragen -> "Verbinden"
--
-- Warum es vorher nicht aufging:
--   DockWidgetPluginGuiInfo.new(...) erwartet als 2. Argument InitialEnabled.
--   Dort stand false - das Widget wurde also unsichtbar erzeugt, und keine
--   Stelle im Skript hat es je wieder eingeschaltet. Jetzt: true, zusaetzlich
--   explizit Enabled = true, ein Toolbar-Knopf "Fenster" und ein Eintrag im
--   Plugins-Menue holen es jederzeit zurueck.

local HttpService = game:GetService("HttpService")
local RunService = game:GetService("RunService")

local SETTING_URL = "ArenaBridgeUrl"
local SETTING_TOKEN = "ArenaBridgeToken"

-- Vorbelegung: wird beim Installieren von der App eingesetzt.
local DEFAULT_URL = "__BRIDGE_URL__"
local DEFAULT_TOKEN = "__BRIDGE_TOKEN__"
local LOCAL_URL = "http://127.0.0.1:8765"
-- Absichtlich zusammengesetzt: so ersetzt der Installer diese Vergleiche nicht.
local PLACEHOLDER_URL = "__BRIDGE_" .. "URL__"
local PLACEHOLDER_TOKEN = "__BRIDGE_" .. "TOKEN__"

local COLORS = {
	bg = Color3.fromRGB(30, 30, 34),
	box = Color3.fromRGB(45, 45, 52),
	text = Color3.fromRGB(235, 235, 240),
	dim = Color3.fromRGB(185, 185, 195),
	faint = Color3.fromRGB(145, 145, 158),
	green = Color3.fromRGB(120, 220, 160),
	red = Color3.fromRGB(240, 130, 130),
	greenBtn = Color3.fromRGB(60, 160, 110),
	redBtn = Color3.fromRGB(165, 75, 75),
}

local function readSetting(key, fallback)
	local ok, value = pcall(function()
		return plugin:GetSetting(key)
	end)
	if ok and typeof(value) == "string" and value ~= "" then
		return value
	end
	return fallback
end

local bridgeUrl = readSetting(SETTING_URL, DEFAULT_URL)
local bridgeToken = readSetting(SETTING_TOKEN, DEFAULT_TOKEN)

local initialUrl = (bridgeUrl or ""):match("^%s*(.-)%s*$")
if initialUrl == "" or initialUrl == PLACEHOLDER_URL then
	initialUrl = LOCAL_URL
end
local initialToken = (bridgeToken or ""):match("^%s*(.-)%s*$")
if initialToken == "" or initialToken == PLACEHOLDER_TOKEN then
	initialToken = ""
end

local ui = {}
local handlers = {}
local state = { enabled = false, loopRunning = false, failures = 0 }

local function trim(text)
	return (tostring(text or ""):gsub("^%s+", ""):gsub("%s+$", ""))
end

local function currentUrl()
	local value = ui.url and ui.url.Text or bridgeUrl
	value = trim(value)
	if value == "" or value == PLACEHOLDER_URL then
		value = LOCAL_URL
	end
	return (value:gsub("/+$", ""))
end

local function currentToken()
	local value = ui.token and ui.token.Text or bridgeToken
	value = trim(value)
	if value == PLACEHOLDER_TOKEN then
		value = ""
	end
	return value
end

--------------------------------------------------------------------------------
-- UI
--------------------------------------------------------------------------------

local function makeLabel(parent, text, height, color, order, textSize)
	local item = Instance.new("TextLabel")
	item.Size = UDim2.new(1, 0, 0, height)
	item.BackgroundTransparency = 1
	item.Font = Enum.Font.Gotham
	item.TextSize = textSize or 13
	item.TextColor3 = color or COLORS.text
	item.Text = text
	item.TextXAlignment = Enum.TextXAlignment.Left
	item.TextYAlignment = Enum.TextYAlignment.Top
	item.TextWrapped = true
	item.LayoutOrder = order
	item.Parent = parent
	return item
end

local function makeBox(parent, placeholder, text, order)
	local item = Instance.new("TextBox")
	item.Size = UDim2.new(1, 0, 0, 32)
	item.BackgroundColor3 = COLORS.box
	item.BorderSizePixel = 0
	item.Font = Enum.Font.Code
	item.TextSize = 13
	item.TextColor3 = COLORS.text
	item.PlaceholderText = placeholder
	item.PlaceholderColor3 = Color3.fromRGB(120, 120, 132)
	item.Text = text or ""
	item.ClearTextOnFocus = false
	item.TextXAlignment = Enum.TextXAlignment.Left
	item.ClipsDescendants = true
	item.LayoutOrder = order
	item.Parent = parent
	return item
end

local function buildContent(host)
	local frame = Instance.new("Frame")
	frame.Name = "Inhalt"
	frame.Size = UDim2.new(1, 0, 1, 0)
	frame.BackgroundColor3 = COLORS.bg
	frame.BorderSizePixel = 0
	frame.Parent = host

	local padding = Instance.new("UIPadding")
	padding.PaddingTop = UDim.new(0, 10)
	padding.PaddingLeft = UDim.new(0, 10)
	padding.PaddingRight = UDim.new(0, 10)
	padding.PaddingBottom = UDim.new(0, 10)
	padding.Parent = frame

	local layout = Instance.new("UIListLayout")
	layout.Padding = UDim.new(0, 6)
	layout.SortOrder = Enum.SortOrder.LayoutOrder
	layout.Parent = frame

	makeLabel(frame, "Arena Studio Connector", 20, COLORS.green, 1, 17)
	makeLabel(frame, "Plugin 1.3  -  Fenster offen. Toolbar-Knopf \"Fenster\" holt es zurueck.",
		26, COLORS.faint, 2, 11)

	makeLabel(frame, "1) Bridge-URL   (in der .bat: \"Lokale URL\")", 16, COLORS.dim, 3, 12)
	ui.url = makeBox(frame, LOCAL_URL, initialUrl, 4)

	makeLabel(frame, "2) Token   (in der .bat: \"Token\")", 16, COLORS.dim, 5, 12)
	ui.token = makeBox(frame, "Token aus der .bat", initialToken, 6)

	ui.connect = Instance.new("TextButton")
	ui.connect.Size = UDim2.new(1, 0, 0, 36)
	ui.connect.BackgroundColor3 = COLORS.greenBtn
	ui.connect.BorderSizePixel = 0
	ui.connect.Font = Enum.Font.GothamMedium
	ui.connect.TextSize = 14
	ui.connect.TextColor3 = Color3.new(1, 1, 1)
	ui.connect.Text = "Verbinden"
	ui.connect.LayoutOrder = 7
	ui.connect.Parent = frame

	ui.status = makeLabel(frame, "Bereit.", 96, COLORS.dim, 8, 12)
	ui.hint = makeLabel(frame,
		"URL + Token werden lokal im Plugin gespeichert (plugin:SetSetting). " ..
		"Der Open-Cloud-Key bleibt in der .bat - das Plugin braucht ihn nicht.",
		56, COLORS.faint, 9, 11)

	return frame
end

-- Notfenster, falls das Dock-Widget nicht erzeugt werden kann
local function buildFallbackWindow()
	local okScreen, screen = pcall(function()
		local s = Instance.new("ScreenGui")
		s.Name = "ArenaBridgeFenster"
		s.ResetOnSpawn = false
		s.DisplayOrder = 9999
		s.ZIndexBehavior = Enum.ZIndexBehavior.Sibling
		s.Parent = game:GetService("CoreGui")
		return s
	end)
	if not okScreen or not screen then
		return nil, nil
	end

	local frame = Instance.new("Frame")
	frame.Name = "ArenaBridge"
	frame.Size = UDim2.new(0, 430, 0, 560)
	frame.Position = UDim2.new(0.5, -215, 0.5, -280)
	frame.BackgroundColor3 = COLORS.bg
	frame.BorderSizePixel = 0
	frame.Active = true
	pcall(function()
		frame.Draggable = true
	end)
	frame.Parent = screen

	local title = Instance.new("TextLabel")
	title.Size = UDim2.new(1, -44, 0, 26)
	title.Position = UDim2.new(0, 10, 0, 2)
	title.BackgroundTransparency = 1
	title.Font = Enum.Font.GothamMedium
	title.TextSize = 14
	title.TextColor3 = COLORS.green
	title.TextXAlignment = Enum.TextXAlignment.Left
	title.Text = "ArenaBridge"
	title.Parent = frame

	local close = Instance.new("TextButton")
	close.Size = UDim2.new(0, 28, 0, 22)
	close.Position = UDim2.new(1, -34, 0, 2)
	close.BackgroundTransparency = 1
	close.Font = Enum.Font.GothamBold
	close.TextSize = 14
	close.TextColor3 = COLORS.dim
	close.Text = "X"
	close.Parent = frame
	close.MouseButton1Click:Connect(function()
		screen.Enabled = false
	end)

	local host = Instance.new("Frame")
	host.Name = "Inhalt"
	host.Size = UDim2.new(1, 0, 1, -26)
	host.Position = UDim2.new(0, 0, 0, 26)
	host.BackgroundTransparency = 1
	host.Parent = frame

	return screen, host
end

local function createWindow()
	local okInfo, info = pcall(function()
		return DockWidgetPluginGuiInfo.new(
			Enum.InitialDockState.Right,
			true, -- InitialEnabled: sofort sichtbar
			true, -- InitialEnabledShouldOverrideRestore: alten "zu"-Zustand nicht uebernehmen
			430, 560, 340, 420
		)
	end)
	if okInfo and info then
		local okGui, widget = pcall(function()
			return plugin:CreateDockWidgetPluginGui("ArenaBridgeDock", info)
		end)
		if okGui and widget then
			pcall(function()
				widget.Title = "ArenaBridge"
				widget.Name = "ArenaBridge"
			end)
			return widget, widget, "dock"
		end
	end

	local screen, host = buildFallbackWindow()
	if screen and host then
		return screen, host, "screen"
	end
	return nil, nil, "keins"
end

local window, host, windowKind = createWindow()
if window and host then
	buildContent(host)
	pcall(function()
		window.Enabled = true
	end)
else
	warn("[ArenaBridge] Konnte kein Fenster erzeugen. Bitte Studio neu starten; " ..
		"falls das nicht hilft, das Plugin ueber /plugin neu installieren.")
end

--------------------------------------------------------------------------------
-- Studio-Handler (unveraendert zur Bridge)
--------------------------------------------------------------------------------

local function resolve(path)
	if typeof(path) ~= "string" or path == "" then
		return nil
	end
	local parts = string.split(path, ".")
	local current = game
	local startIndex = 1
	if parts[1] == "game" then
		startIndex = 2
	end
	for index = startIndex, #parts do
		local name = parts[index]
		if current == game then
			local ok, service = pcall(function()
				return game:GetService(name)
			end)
			if ok and service then
				current = service
			else
				local child = current:FindFirstChild(name)
				if not child then
					return nil
				end
				current = child
			end
		else
			local child = current:FindFirstChild(name)
			if not child then
				return nil
			end
			current = child
		end
	end
	return current
end

local function pathOf(instance)
	local names = {}
	local current = instance
	while current and current ~= game do
		table.insert(names, 1, current.Name)
		current = current.Parent
	end
	return "game." .. table.concat(names, ".")
end

local function convert(value)
	if typeof(value) == "table" and value._type then
		local kind = value._type
		if kind == "Vector3" then
			return Vector3.new(value.x or 0, value.y or 0, value.z or 0)
		end
		if kind == "Color3" then
			return Color3.fromRGB(value.r or 255, value.g or 255, value.b or 255)
		end
		if kind == "UDim2" then
			return UDim2.new(value.xs or 0, value.xo or 0, value.ys or 0, value.yo or 0)
		end
		if kind == "Enum" and typeof(value.value) == "string" then
			local enum = Enum
			for part in string.gmatch(value.value, "[^%.]+") do
				enum = enum[part]
			end
			return enum
		end
	end
	return value
end

local function describe(instance, depth, maxDepth)
	local info = {
		name = instance.Name,
		className = instance.ClassName,
		path = pathOf(instance),
		children = {},
	}
	if depth < maxDepth then
		for _, child in ipairs(instance:GetChildren()) do
			table.insert(info.children, describe(child, depth + 1, maxDepth))
		end
	end
	return info
end

handlers.place_info = function()
	return {
		placeId = game.PlaceId,
		universeId = game.GameId,
		name = game.Name,
		jobId = game.JobId,
		isStudio = RunService:IsStudio(),
	}
end

handlers.list_children = function(args)
	local instance = resolve(args.path)
	assert(instance, "Pfad nicht gefunden: " .. tostring(args.path))
	local out = {}
	for _, child in ipairs(instance:GetChildren()) do
		table.insert(out, {
			name = child.Name,
			className = child.ClassName,
			path = pathOf(child),
		})
	end
	return out
end

handlers.get_tree = function(args)
	local instance = resolve(args.path or "game.Workspace")
	assert(instance, "Pfad nicht gefunden: " .. tostring(args.path))
	return describe(instance, 0, tonumber(args.depth) or 2)
end

handlers.get_script = function(args)
	local instance = resolve(args.path)
	assert(instance, "Pfad nicht gefunden: " .. tostring(args.path))
	assert(instance:IsA("LuaSourceContainer"), "Kein Script: " .. tostring(args.path))
	return { path = args.path, source = instance.Source }
end

handlers.set_script = function(args)
	local instance = resolve(args.path)
	assert(instance, "Pfad nicht gefunden: " .. tostring(args.path))
	assert(instance:IsA("LuaSourceContainer"), "Kein Script: " .. tostring(args.path))
	instance.Source = args.source or ""
	return { path = args.path, ok = true }
end

handlers.create_instance = function(args)
	local parent = resolve(args.parent or "game.Workspace")
	assert(parent, "Parent nicht gefunden: " .. tostring(args.parent))
	local instance = Instance.new(args.className)
	instance.Name = args.name or args.className
	if args.properties then
		for key, value in pairs(args.properties) do
			pcall(function()
				instance[key] = convert(value)
			end)
		end
	end
	instance.Parent = parent
	return { path = pathOf(instance), className = instance.ClassName }
end

handlers.set_property = function(args)
	local instance = resolve(args.path)
	assert(instance, "Pfad nicht gefunden: " .. tostring(args.path))
	instance[args.property] = convert(args.value)
	return { path = args.path, property = args.property }
end

handlers.delete_instance = function(args)
	local instance = resolve(args.path)
	assert(instance, "Pfad nicht gefunden: " .. tostring(args.path))
	local path = pathOf(instance)
	instance:Destroy()
	return { deleted = path }
end

handlers.execute_luau = function(args)
	assert(typeof(args.code) == "string", "code fehlt")
	local chunk, err = loadstring(args.code)
	assert(chunk, "loadstring-Fehler (ggf. 'LoadStringEnabled' aktivieren): " .. tostring(err))
	local results = { chunk() }
	local texts = {}
	for _, value in ipairs(results) do
		table.insert(texts, tostring(value))
	end
	return { returned = table.concat(texts, ", ") }
end

--------------------------------------------------------------------------------
-- Verbindung zur Bridge
--------------------------------------------------------------------------------

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

local function heartbeat()
	pcall(request, "POST", "/plugin/heartbeat", handlers.place_info())
end

local lastStatusText = nil

local function setStatus(text, kind)
	if ui.status then
		ui.status.Text = text
		if kind == true then
			ui.status.TextColor3 = COLORS.green
		elseif kind == false then
			ui.status.TextColor3 = COLORS.red
		else
			ui.status.TextColor3 = COLORS.dim
		end
	end
	if text ~= lastStatusText then
		lastStatusText = text
		print("[ArenaBridge] " .. tostring(text):gsub("\n", " | "))
	end
end

local function handleCommand(cmd)
	local okCmd, result = pcall(function()
		local handler = handlers[cmd.type]
		assert(handler, "Unbekanntes Kommando: " .. tostring(cmd.type))
		return handler(cmd.args or {})
	end)
	pcall(request, "POST", "/plugin/result", {
		id = cmd.id,
		ok = okCmd,
		result = okCmd and result or nil,
		error = (not okCmd) and tostring(result) or nil,
	})
end

local function connectionLoop()
	local lastBeat = 0
	while state.enabled do
		local ok, response = pcall(request, "GET", "/plugin/poll")
		if not ok then
			state.failures = state.failures + 1
			local message = tostring(response)
			local lower = string.lower(message)
			if string.find(lower, "not enabled", 1, true)
				or string.find(lower, "not allowed", 1, true)
				or string.find(lower, "http requests", 1, true) then
				message = message ..
					"\n-> Startseite -> Game Settings -> Security -> \"Allow HTTP Requests\" aktivieren."
			end
			setStatus("Keine Verbindung zu " .. currentUrl() ..
				" (Versuch " .. tostring(state.failures) .. ")\n" .. message, false)
			task.wait(math.min(1 + state.failures, 5))
		elseif response.StatusCode == 401 then
			setStatus("Token falsch (HTTP 401).\nBitte den Token aus der .bat neu eintragen.", false)
			state.enabled = false
		elseif not response.Success then
			setStatus("Bridge antwortet mit HTTP " .. tostring(response.StatusCode) ..
				".\nLaeuft die richtige .bat? Stimmt die URL?", false)
			task.wait(2)
		else
			state.failures = 0
			setStatus("Verbunden - " .. tostring(game.Name) ..
				"\nPlaceId " .. tostring(game.PlaceId), true)

			local okDecode, decoded = pcall(function()
				return HttpService:JSONDecode(response.Body)
			end)
			local cmd = okDecode and decoded and decoded.command or nil
			if cmd then
				handleCommand(cmd)
			end

			if os.clock() - lastBeat > 5 then
				heartbeat()
				lastBeat = os.clock()
			end
			task.wait(0.7)
		end
	end
end

local function startConnection()
	local url = currentUrl()
	local token = currentToken()
	if url == "" or not string.match(url, "^https?://") then
		setStatus("Bitte eine Bridge-URL angeben, z. B. " .. LOCAL_URL, false)
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

	state.enabled = true
	state.failures = 0
	if ui.connect then
		ui.connect.Text = "Trennen"
		ui.connect.BackgroundColor3 = COLORS.redBtn
	end
	setStatus("Verbinde mit " .. url .. " ...", nil)

	if not state.loopRunning then
		state.loopRunning = true
		task.spawn(function()
			local ok, err = pcall(connectionLoop)
			if not ok then
				warn("[ArenaBridge] Verbindungsschleife beendet: " .. tostring(err))
				state.enabled = false
			end
			state.loopRunning = false
			if ui.connect then
				ui.connect.Text = "Verbinden"
				ui.connect.BackgroundColor3 = COLORS.greenBtn
			end
			setStatus("Getrennt.", nil)
		end)
	end
end

local function stopConnection()
	if not state.enabled then
		return
	end
	state.enabled = false
	if ui.connect then
		ui.connect.Text = "Verbinden"
		ui.connect.BackgroundColor3 = COLORS.greenBtn
	end
	setStatus("Getrennt.", nil)
end

if ui.connect then
	ui.connect.MouseButton1Click:Connect(function()
		if state.enabled then
			stopConnection()
		else
			startConnection()
		end
	end)
end

--------------------------------------------------------------------------------
-- Toolbar + Plugins-Menue: Fenster jederzeit zurueckholen
--------------------------------------------------------------------------------

local function setWindowVisible(visible)
	if window then
		pcall(function()
			window.Enabled = visible and true or false
		end)
	end
end

local okToolbar, toolbar = pcall(function()
	return plugin:CreateToolbar("Arena AI")
end)
if okToolbar and toolbar then
	local okOpen, openButton = pcall(function()
		return toolbar:CreateButton("Fenster", "ArenaBridge-Fenster oeffnen/schliessen",
			"rbxassetid://4458901886")
	end)
	if okOpen and openButton then
		openButton.ClickableWhenViewportHidden = true
		openButton.Click:Connect(function()
			setWindowVisible(not (window and window.Enabled))
		end)
	end

	local okConnect, connectButton = pcall(function()
		return toolbar:CreateButton("Verbinden", "Mit der Arena-Bridge verbinden/trennen",
			"rbxassetid://4458901886")
	end)
	if okConnect and connectButton then
		connectButton.ClickableWhenViewportHidden = true
		connectButton.Click:Connect(function()
			if state.enabled then
				stopConnection()
			else
				startConnection()
			end
		end)
	end
else
	warn("[ArenaBridge] Toolbar konnte nicht angelegt werden: " .. tostring(toolbar))
end

local okAction, openAction = pcall(function()
	return plugin:CreatePluginAction("ArenaBridgeOeffnen", "ArenaBridge oeffnen",
		"Fenster des Arena Studio Connectors anzeigen", "", true)
end)
if okAction and openAction then
	openAction.Triggered:Connect(function()
		setWindowVisible(true)
	end)
end

--------------------------------------------------------------------------------
-- Start
--------------------------------------------------------------------------------

if window == nil then
	setStatus("Kein Fenster moeglich - bitte Studio neu starten. Die Toolbar " ..
		"\"Verbinden\" funktioniert trotzdem.", false)
elseif currentToken() ~= "" then
	task.delay(1, function()
		if not state.enabled then
			startConnection()
		end
	end)
else
	setStatus("Bereit.\n1) Bridge-URL pruefen   2) Token eintragen   3) \"Verbinden\" klicken.", nil)
end

print("[ArenaBridge] Geladen (Fenster: " .. tostring(windowKind) ..
	"). URL + Token aus der .bat eintragen, dann 'Verbinden'.")
