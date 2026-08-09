grammar StockDsl;

options { caseInsensitive = true; }

query
    : SCREEN ON DATE
      (WHERE expression)?
      (ADJUST adjustmentMode)?
      (ORDER BY expression direction?)?
      (LIMIT INT)?
      EOF
    ;

adjustmentMode : FORWARD | BACKWARD | NONE;
direction      : ASC | DESC;

expression     : orExpression;
orExpression   : andExpression (OR andExpression)*;
andExpression  : notExpression (AND notExpression)*;
notExpression  : NOT notExpression | predicate;
predicate
    : additiveExpression
      ( comparisonOperator additiveExpression
      | BETWEEN additiveExpression AND additiveExpression
      | IN listLiteral
      )?
    ;
comparisonOperator : EQ | NE | GT | GE | LT | LE;
additiveExpression       : multiplicativeExpression ((PLUS | MINUS) multiplicativeExpression)*;
multiplicativeExpression : unaryExpression ((STAR | SLASH) unaryExpression)*;
unaryExpression          : (PLUS | MINUS) unaryExpression | primary;
primary                  : functionCall | identifier | literal | LPAREN expression RPAREN;
functionCall             : identifier LPAREN argumentList? RPAREN;
argumentList             : expression (COMMA expression)*;
identifier               : IDENTIFIER;
listLiteral              : LBRACK (literal (COMMA literal)*)? RBRACK;
literal                  : PERCENT | DECIMAL | INT | STRING | DATE | TRUE | FALSE | NULL;

SCREEN   : 'SCREEN';
ON       : 'ON';
WHERE    : 'WHERE';
ADJUST   : 'ADJUST';
FORWARD  : 'FORWARD';
BACKWARD : 'BACKWARD';
NONE     : 'NONE';
ORDER    : 'ORDER';
BY       : 'BY';
ASC      : 'ASC';
DESC     : 'DESC';
LIMIT    : 'LIMIT';
AND      : 'AND';
OR       : 'OR';
NOT      : 'NOT';
BETWEEN  : 'BETWEEN';
IN       : 'IN';
TRUE     : 'TRUE';
FALSE    : 'FALSE';
NULL     : 'NULL';

GE      : '>=';
LE      : '<=';
NE      : '!=' | '<>';
EQ      : '=';
GT      : '>';
LT      : '<';
PLUS    : '+';
MINUS   : '-';
STAR    : '*';
SLASH   : '/';
LPAREN  : '(';
RPAREN  : ')';
LBRACK  : '[';
RBRACK  : ']';
COMMA   : ',';

DATE       : DIGIT DIGIT DIGIT DIGIT '-' DIGIT DIGIT '-' DIGIT DIGIT;
PERCENT    : (DIGIT+ ('.' DIGIT+)?) '%';
DECIMAL    : DIGIT+ '.' DIGIT+;
INT        : DIGIT+;
STRING     : '\'' ('\'\'' | ~'\'')* '\'';
IDENTIFIER : [A-Z_] [A-Z_0-9]*;

LINE_COMMENT : '--' ~[\r\n]* -> skip;
WS           : [ \t\r\n]+ -> skip;
fragment DIGIT : [0-9];
