pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// History tab: the project's branches (left) and the commits of the selected
// branch (right). Dialogs (names, confirmations) live in Main.qml; this page
// only asks for them through signals.
Rectangle {
	id: root

	signal commitRequested()
	// fromCommit "" = from the current state of the current branch.
	signal newBranchRequested(string fromCommit, string label)
	signal renameRequested(string name)
	signal deleteRequested(string name, int commitCount)
	signal restoreRequested(string commitId, string message)

	color: "#17191d"

	component SectionTitle: Text {
		color: "#929ba8"
		font.pixelSize: 10
		font.weight: Font.Bold
		font.letterSpacing: 1.4
	}

	component Hint: Text {
		color: "#687280"
		font.pixelSize: 11
		wrapMode: Text.WordWrap
	}

	// "just now", "5 min ago", "3 h ago", "yesterday 14:05", "12 Oct 2026 14:05".
	function relativeTime(ms) {
		if (!ms)
			return ""
		var date = new Date(ms)
		var seconds = (Date.now() - ms) / 1000
		var clock = date.toLocaleTimeString(Qt.locale(), "HH:mm")
		if (seconds < 60)
			return "just now"
		if (seconds < 3600)
			return Math.floor(seconds / 60) + " min ago"
		var today = new Date()
		today.setHours(0, 0, 0, 0)
		if (ms >= today.getTime())
			return Math.floor(seconds / 3600) + " h ago"
		if (ms >= today.getTime() - 86400000)
			return "yesterday " + clock
		return date.toLocaleDateString(Qt.locale(), "d MMM yyyy") + " " + clock
	}

	// Refresh the relative times now and then.
	property int tick: 0
	Timer {
		interval: 30000
		running: root.visible
		repeat: true
		onTriggered: root.tick++
	}

	RowLayout {
		anchors.fill: parent
		spacing: 0

		// -- Branches -------------------------------------------------------
		Rectangle {
			Layout.preferredWidth: 300
			Layout.fillHeight: true
			color: "#1b1e23"
			border.color: "#2b3038"

			ColumnLayout {
				anchors.fill: parent
				anchors.margins: 16
				spacing: 10

				RowLayout {
					Layout.fillWidth: true
					SectionTitle { text: "BRANCHES" }
					Item { Layout.fillWidth: true }
					VButton {
						text: "New Branch…"
						onClicked: root.newBranchRequested("", "")
					}
				}
				Hint {
					Layout.fillWidth: true
					text: "Each branch is its own version of the program. Uncommitted changes stay with their branch when you switch."
				}

				ListView {
					Layout.fillWidth: true
					Layout.fillHeight: true
					clip: true
					spacing: 6
					model: project.branches
					boundsBehavior: Flickable.StopAtBounds

					delegate: Rectangle {
						id: branchEntry
						required property var modelData
						readonly property bool shown: modelData.name === project.historyBranch

						width: ListView.view.width
						implicitHeight: branchInfo.implicitHeight + 18
						radius: 5
						color: shown ? "#262c36" : branchMouse.containsMouse ? "#22262d" : "#20242b"
						border.color: shown ? "#72a7ff" : "#383d46"

						MouseArea {
							id: branchMouse
							anchors.fill: parent
							hoverEnabled: true
							cursorShape: Qt.PointingHandCursor
							onClicked: project.setHistoryBranch(branchEntry.modelData.name)
							onDoubleClicked: project.switchBranch(branchEntry.modelData.name)
						}

						ColumnLayout {
							id: branchInfo
							anchors.left: parent.left
							anchors.right: branchButtons.left
							anchors.leftMargin: 12
							anchors.rightMargin: 6
							anchors.verticalCenter: parent.verticalCenter
							spacing: 3

							RowLayout {
								Layout.fillWidth: true
								spacing: 6
								Text {
									Layout.fillWidth: true
									text: "⎇ " + branchEntry.modelData.name
									color: "#e3e7ed"
									font.pixelSize: 13
									font.weight: branchEntry.modelData.isCurrent ? Font.DemiBold : Font.Normal
									elide: Text.ElideRight
								}
								Text {
									visible: branchEntry.modelData.isCurrent
									text: "CURRENT"
									color: "#72a7ff"
									font.pixelSize: 9
									font.weight: Font.Bold
									font.letterSpacing: 1
								}
							}
							RowLayout {
								Layout.fillWidth: true
								spacing: 6
								Text {
									visible: branchEntry.modelData.hasDraft
									text: "• uncommitted"
									color: "#f59e0b"
									font.pixelSize: 11
								}
								Text {
								Layout.fillWidth: true
								text: {
									root.tick
									var m = branchEntry.modelData
									return m.commitCount === 0 ? "No commits yet"
										: m.message + "  ·  " + root.relativeTime(m.time)
								}
								color: "#929ba8"
								font.pixelSize: 11
								elide: Text.ElideRight
								}
							}
						}

						Row {
							id: branchButtons
							anchors.right: parent.right
							anchors.rightMargin: 8
							anchors.verticalCenter: parent.verticalCenter
							spacing: 2

							VButton {
								subtle: true
								text: "✎"
								implicitWidth: 26
								leftPadding: 0
								rightPadding: 0
								ToolTip.visible: hovered
								ToolTip.delay: 500
								ToolTip.text: "Rename"
								onClicked: root.renameRequested(branchEntry.modelData.name)
							}
							VButton {
								subtle: true
								visible: !branchEntry.modelData.isCurrent
								text: "✕"
								implicitWidth: 26
								leftPadding: 0
								rightPadding: 0
								ToolTip.visible: hovered
								ToolTip.delay: 500
								ToolTip.text: "Delete"
								onClicked: root.deleteRequested(branchEntry.modelData.name,
									branchEntry.modelData.commitCount)
							}
						}
					}
				}
			}
		}

		// -- Commits of the selected branch ---------------------------------
		ColumnLayout {
			id: commitsPane
			Layout.fillWidth: true
			Layout.fillHeight: true
			Layout.margins: 24
			spacing: 12

			readonly property bool showingCurrent: project.historyBranch === project.currentBranch

			RowLayout {
				Layout.fillWidth: true
				spacing: 10

				Text {
					Layout.fillWidth: true
					text: "⎇ " + project.historyBranch
					color: "#e3e7ed"
					font.pixelSize: 18
					font.weight: Font.DemiBold
					elide: Text.ElideRight
				}
				VButton {
					visible: !commitsPane.showingCurrent
					text: "Switch to Branch"
					kind: "primary"
					onClicked: project.switchBranch(project.historyBranch)
				}
				VButton {
					visible: commitsPane.showingCurrent
					text: "Commit…"
					kind: "primary"
					enabled: project.hasUncommittedChanges
					onClicked: root.commitRequested()
				}
			}

			// Uncommitted changes on the current branch, shown as the top entry.
			Rectangle {
				Layout.fillWidth: true
				visible: commitsPane.showingCurrent && project.hasUncommittedChanges
				implicitHeight: 40
				radius: 5
				color: "#2a2418"
				border.color: "#6b5220"

				Text {
					anchors.fill: parent
					anchors.leftMargin: 14
					verticalAlignment: Text.AlignVCenter
					text: {
						var summary = project.hasCommits ? project.uncommittedSummary() : ""
						return "Uncommitted changes" + (summary ? "  ·  " + summary : "")
					}
					color: "#f5c46b"
					font.pixelSize: 12
				}
			}

			Hint {
				visible: project.historyLog.length === 0
				Layout.fillWidth: true
				text: "No commits on this branch yet. A commit saves the current version of the program "
					+ "(graph, compile settings, colours and imported nodes) so you can come back to it."
				color: "#929ba8"
			}

			ListView {
				id: commitList
				Layout.fillWidth: true
				Layout.fillHeight: true
				clip: true
				spacing: 0
				model: project.historyLog
				boundsBehavior: Flickable.StopAtBounds
				ScrollBar.vertical: ScrollBar {}

				delegate: Item {
					id: commitEntry
					required property var modelData
					required property int index

					width: ListView.view.width
					implicitHeight: 58

					// Timeline: a line through the dots, the newest commit filled.
					Rectangle {
						x: 11
						width: 2
						y: commitEntry.index === 0 ? parent.height / 2 : 0
						height: (commitEntry.index === commitList.count - 1 ? parent.height / 2 : parent.height) - y
						color: "#3a404a"
					}
					Rectangle {
						x: 6
						anchors.verticalCenter: parent.verticalCenter
						width: 12
						height: 12
						radius: 6
						color: commitEntry.modelData.isHead ? "#72a7ff" : "#17191d"
						border.color: "#72a7ff"
						border.width: 2
					}

					Rectangle {
						anchors.fill: parent
						anchors.leftMargin: 28
						anchors.topMargin: 3
						anchors.bottomMargin: 3
						radius: 5
						color: commitMouse.containsMouse ? "#20242b" : "transparent"

						MouseArea {
							id: commitMouse
							anchors.fill: parent
							hoverEnabled: true
						}

						ColumnLayout {
							anchors.left: parent.left
							anchors.right: commitButtons.left
							anchors.leftMargin: 10
							anchors.rightMargin: 10
							anchors.verticalCenter: parent.verticalCenter
							spacing: 3

							Text {
								Layout.fillWidth: true
								text: commitEntry.modelData.message
								color: "#e3e7ed"
								font.pixelSize: 13
								elide: Text.ElideRight
							}
							Text {
								Layout.fillWidth: true
								text: {
									root.tick
									var m = commitEntry.modelData
									return root.relativeTime(m.time) + (m.summary ? "  ·  " + m.summary : "")
								}
								color: "#929ba8"
								font.pixelSize: 11
								elide: Text.ElideRight
							}
						}

						Row {
							id: commitButtons
							anchors.right: parent.right
							anchors.rightMargin: 8
							anchors.verticalCenter: parent.verticalCenter
							spacing: 6
							visible: commitMouse.containsMouse || restoreButton.hovered || branchButton.hovered

							Text {
								anchors.verticalCenter: parent.verticalCenter
								text: commitEntry.modelData.id.slice(0, 7)
								color: "#687280"
								font.pixelSize: 10
								font.family: monoFont
							}
							VButton {
								id: branchButton
								text: "New Branch Here…"
								onClicked: root.newBranchRequested(commitEntry.modelData.id, commitEntry.modelData.message)
							}
							VButton {
								id: restoreButton
								text: "Restore"
								visible: commitsPane.showingCurrent
								onClicked: root.restoreRequested(commitEntry.modelData.id, commitEntry.modelData.message)
							}
						}
					}
				}
			}
		}
	}
}
