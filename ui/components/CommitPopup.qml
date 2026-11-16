pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// Commit the current state of the project on the current branch.
//   Enter: commit    Escape / click outside: cancel
Popup {
	id: root

	// The message was accepted; Main.qml does the commit (and saving).
	signal commitRequested(string message)

	property string summary: ""

	parent: Overlay.overlay
	anchors.centerIn: parent
	width: 460
	modal: true
	dim: true
	padding: 20
	closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside

	background: Rectangle {
		color: "#202329"
		radius: 8
		border.color: "#383d46"
	}

	function commit() {
		if (messageField.text.trim() === "")
			return
		var message = messageField.text
		close()
		commitRequested(message)
	}

	onAboutToShow: {
		summary = project.uncommittedSummary()
		messageField.text = ""
	}
	onOpened: messageField.forceActiveFocus()

	ColumnLayout {
		width: parent.width
		spacing: 12

		Text {
			Layout.fillWidth: true
			text: "Commit to " + project.currentBranch
			color: "#e3e7ed"
			font.pixelSize: 15
			font.weight: Font.DemiBold
			elide: Text.ElideRight
		}

		Text {
			Layout.fillWidth: true
			text: root.summary ? "Changes since the last commit: " + root.summary
				: project.hasCommits ? "" : "The first commit of this branch."
			visible: text !== ""
			color: "#929ba8"
			font.pixelSize: 12
			wrapMode: Text.WordWrap
		}

		VTextField {
			id: messageField
			Layout.fillWidth: true
			placeholderText: "What changed? e.g. “slow down near walls”"
			onAccepted: root.commit()
		}

		RowLayout {
			Layout.fillWidth: true
			Layout.topMargin: 6
			spacing: 8

			Text {
				Layout.fillWidth: true
				text: project.hasFilePath ? "Ctrl+K  ·  also saves the project" : "Ctrl+K"
				color: "#687280"
				font.pixelSize: 11
			}

			VButton {
				text: "Cancel"
				onClicked: root.close()
			}
			VButton {
				text: "Commit"
				kind: "primary"
				enabled: messageField.text.trim() !== ""
				onClicked: root.commit()
			}
		}
	}
}
