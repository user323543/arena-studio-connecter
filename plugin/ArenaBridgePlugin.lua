-- ArenaBridgePlugin.lua  –  Arena AI <-> Roblox Studio Bridge
-- Wird von der Connector-App beim Start AUTOMATISCH installiert:
--   %LOCALAPPDATA%\Roblox\Plugins\ArenaBridgePlugin.lua
-- Platzhalter unten werden dabei durch die echten Werte ersetzt.
-- Das Plugin spricht NUR mit 127.0.0.1 (dein PC), niemals direkt mit dem Internet.
local BRIDGE_URL = "__BRIDGE_URL__"       -- z. B. http://127.0.0.1:8765
local BRIDGE_TOKEN = "__BRIDGE_TOKEN__"   -- gleicher Token wie in der App

local HttpService = game:GetService("HttpService")
local toolbar = plugin:CreateToolbar("Arena AI")
local button = toolbar:CreateButton("ArenaBridge", "Mit Arena-Bridge verbinden/trennen", "rbxassetid://0")
button.ClickableWhenViewportHidden = true

local enabled = false
button:SetActive(false)

local function headers()
	return {
		["Authorization"] = "Bearer " .. BRIDGE_TOKEN,
		["Content-Type"] = "application/json",
	}
end

local function request(method, path, body)
	return HttpService:RequestAsync({
		Url = BRIDGE_URL .. path,
		Method = method,
		Headers = headers(),
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
		end
		if os.clock() - lastBeat > 5 then heartbeat(); lastBeat = os.clock() end
		task.wait(0.8)
	end
end

button.Click:Connect(function()
	enabled = not enabled
	button:SetActive(enabled)
	if enabled then
		print("[ArenaBridge] Verbinde mit " .. BRIDGE_URL .. " – PlaceId " .. tostring(game.PlaceId))
		task.spawn(loop)
	else
		print("[ArenaBridge] Getrennt.")
	end
end)

print("[ArenaBridge] Geladen. Toolbar-Button 'ArenaBridge' klicken zum Verbinden.")
